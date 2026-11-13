#!/usr/bin/python3
"""Read-only checks; never dump credentials, pairing, serials or host addresses."""
import argparse
import json
import os
from pathlib import Path
import sys
from guard_config import SETTINGS,config_path,read_credentials
from sunshine_observer import read_snapshot,input_health,source_hash


def diagnose():
    value=read_snapshot()
    checks=dict(configured=config_path().is_file(),observer_fresh=value is not None,
                observer_source_matches=bool(value and value.get('source_sha256')==source_hash()),
                observer_video_port_matches=bool(value and value.get('video_port')==SETTINGS.video_port),
                input_coverage=input_health(value),capture_sync_enabled=SETTINGS.follow_primary)
    try:
        read_credentials(SETTINGS.restart_credentials)
        checks['restart_credentials_private']=True
    except (TypeError,OSError,ValueError):checks['restart_credentials_private']=False
    connector=SETTINGS.reserve_connector
    drm_name=connector.replace('HDMI-','HDMI-A-',1) if connector and connector.startswith('HDMI-') else connector
    nodes=list(Path('/sys/class/drm').glob('card*-'+drm_name+'/status')) if drm_name else []
    checks['reserve_drm_unambiguous']=len(nodes)==1
    try:
        from sunshine_session_display import Display
        d=Display()
        checks.update(graphical_session=True,reserve_available=SETTINGS.reserve_connector in d.modes,
                      reserve_active=any(m[0]==SETTINGS.reserve_connector for row in d.layout for m in row[-1]))
    except Exception as error:
        checks.update(graphical_session=False,error_type=type(error).__name__)
    try:
        from sunshine_session_display import invocation_id
        checks['sunshine_running']=bool(invocation_id())
    except Exception as error:
        checks.update(sunshine_running=False,sunshine_error_type=type(error).__name__)
    ready=(checks['configured'] and SETTINGS.reserve_connector is not None and
           checks['capture_sync_enabled'] and checks['restart_credentials_private'] and
           checks['observer_fresh'] and checks['observer_source_matches'] and
           checks['observer_video_port_matches'] and checks['input_coverage'] in ('ready','no_devices') and
           checks['reserve_drm_unambiguous'] and
           checks.get('reserve_available') and checks.get('sunshine_running'))
    return dict(ready=bool(ready),checks=checks,panel_power='unknown')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--require-ready',action='store_true')
    args=p.parse_args();result=diagnose();print(json.dumps(result,indent=2))
    return 1 if args.require_ready and not result['ready'] else 0


if __name__=='__main__':raise SystemExit(main())
