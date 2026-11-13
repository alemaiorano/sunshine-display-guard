"""Run actual immutable deployment and rollback against a fake service boundary."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installer',ROOT/'scripts/install.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.prefix=self.base/'prefix';self.prefix.mkdir()
        self.account=types.SimpleNamespace(pw_name='fixture-user',pw_uid=os.getuid(),pw_gid=os.getgid(),pw_dir=str(self.base/'home'))
        for name,value in [('PREFIX',self.prefix),('SYSTEM',self.base/'system'),('USER',self.base/'user'),('STATE',self.base/'observer.json'),('INSTALL_LOCK',self.base/'install.lock')]:
            p=patch.object(installer,name,value);p.start();self.addCleanup(p.stop)
        self.old=self.prefix/'releases'/'old';self.old.mkdir(parents=True)
        self.files=installer.payload()
        for name in self.files:(self.old/name).write_text('# previous\n')
        (self.prefix/'current').symlink_to(self.old)
        installer.SYSTEM.mkdir();installer.USER.mkdir()
        (installer.SYSTEM/installer.OBSERVER).write_text('# previous unit\n')
        (installer.USER/installer.POLICY).write_text('# previous user unit\n')
        self.active=True;self.policy=True;self.enabled=True;self.fail=None;self.calls=[]
        self.pid=1;self.snapshot()
        p=patch.object(installer,'run',side_effect=self.fake_run);p.start();self.addCleanup(p.stop)
    def snapshot(self):
        now=time.monotonic()
        source=(self.prefix/'current'/'sunshine_observer.py').read_bytes()
        installer.STATE.write_text(json.dumps(dict(schema=2,boot_id=installer.BOOT.read_text().strip(),producer_pid=self.pid,source_sha256=hashlib.sha256(source).hexdigest(),observed_at=now,producer_started_at=now,input_scan_at=now,input_eligible=0,input_opened=0,input_errors=0,video_at=0)))
    def fake_run(self,args,check=True):
        self.calls.append(args)
        user='--user' in args
        command=args[args.index('--user')+1] if user else args[1]
        code=0;stdout=''
        if self.fail==(user,command):
            self.fail=None;code=1
        elif command=='is-active':code=0 if (self.policy if user else self.active) else 3
        elif command=='is-enabled':code=0 if self.enabled else 1
        elif command=='enable':self.enabled=True
        elif command=='disable':self.enabled=False
        elif command=='stop':
            if user:self.policy=False
            else:self.active=False
        elif command in ('start','restart'):
            if user:self.policy=True
            else:self.active=True;self.pid+=1;self.snapshot()
        elif command=='show':stdout=str(self.pid)
        if check and code:raise installer.subprocess.CalledProcessError(code,args)
        return types.SimpleNamespace(returncode=code,stdout=stdout,stderr='')
    def apply(self):installer.apply(self.account,self.files)
    def test_upgrade_changes_immutable_release_and_attests(self):
        self.apply();self.assertNotEqual((self.prefix/'current').resolve(),self.old)
        self.assertTrue(self.active);self.assertTrue(self.policy)
        self.assertEqual((self.old/'sunshine_observer.py').read_text(),'# previous\n')
    def test_restart_failure_rolls_back(self):
        self.fail=(False,'restart')
        with self.assertRaises(installer.subprocess.CalledProcessError):self.apply()
        self.assertEqual((self.prefix/'current').resolve(),self.old);self.assertTrue(self.active);self.assertTrue(self.policy)
    def test_consumer_failure_rolls_back(self):
        self.fail=(True,'start')
        with self.assertRaises(installer.subprocess.CalledProcessError):self.apply()
        self.assertEqual((self.prefix/'current').resolve(),self.old);self.assertTrue(self.policy)
    def test_first_install_does_not_start_user_policy(self):
        (self.prefix/'current').unlink();self.active=self.policy=self.enabled=False
        self.apply();self.assertTrue(self.active);self.assertFalse(self.policy)
    def test_video_refuses_before_changing_release(self):
        v=json.loads(installer.STATE.read_text());v['video_at']=time.monotonic();installer.STATE.write_text(json.dumps(v))
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual((self.prefix/'current').resolve(),self.old);self.assertTrue(self.active)
    def test_masked_unit_is_not_overwritten(self):
        p=installer.SYSTEM/installer.OBSERVER;p.unlink();p.symlink_to('/dev/null')
        with self.assertRaises(ValueError):self.apply()
        self.assertTrue(p.is_symlink());self.assertEqual((self.prefix/'current').resolve(),self.old)
    def test_same_release_is_verified_not_overwritten(self):
        self.apply();release=(self.prefix/'current').resolve()
        (release/'guard_config.py').write_text('# corruption\n')
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual((release/'guard_config.py').read_text(),'# corruption\n')
    def test_world_writable_prefix_is_rejected(self):
        self.prefix.chmod(0o777)
        with self.assertRaises(ValueError):self.apply()
        self.assertTrue(self.active)
    def test_symlinked_global_lock_is_rejected(self):
        other=self.base/'other';other.write_text('untouched')
        installer.INSTALL_LOCK.symlink_to(other)
        with self.assertRaises(OSError):self.apply()
        self.assertEqual(other.read_text(),'untouched')
    def test_foreign_current_target_is_rejected(self):
        p=self.prefix/'current';p.unlink();p.symlink_to(self.base)
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(p.resolve(),self.base)
    def test_missing_user_bus_is_rejected_before_privileged_apply(self):
        import sys
        with patch.object(sys,'argv',['install','--user','fixture-user','--apply']),patch.object(installer.pwd,'getpwnam',return_value=self.account),patch.object(installer.os,'geteuid',return_value=0),patch.object(installer.Path,'is_socket',return_value=False),patch.object(installer,'apply') as apply:
            with self.assertRaises(ValueError):installer.main()
        apply.assert_not_called()
    def test_unreachable_user_manager_refuses_before_changing_release(self):
        self.fail=(True,'show')
        with self.assertRaises(installer.subprocess.CalledProcessError):self.apply()
        self.assertEqual((self.prefix/'current').resolve(),self.old)
        self.assertTrue(self.active);self.assertTrue(self.policy)
