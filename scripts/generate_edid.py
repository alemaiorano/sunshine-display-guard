#!/usr/bin/python3
"""Write an offline EDID fixture. Does not install firmware or touch DRM."""
import argparse
import sys


def timing(clock,horizontal,vertical,flags=0x1A):
    w,hs,he,ht=horizontal;h,vs,ve,vt=vertical
    hb,vb=ht-w,vt-h;hp,hw=hs-w,he-hs;vp,vw=vs-h,ve-vs
    return clock.to_bytes(2,'little')+bytes([
        w&255,hb&255,(w>>8)<<4|hb>>8,h&255,vb&255,(h>>8)<<4|vb>>8,
        hp&255,hw&255,(vp&15)<<4|(vw&15),(hp>>8)<<6|(hw>>8)<<4|(vp>>4)<<2|vw>>4,
        0,0,0,0,0,flags])


def reduced(width,height,fps,max_clock):
    if not 64<=width<=4095 or not 64<=height<=4095 or not 1<=fps<=240:
        raise ValueError('DTD modes require dimensions 64..4095 and FPS 1..240')
    blank=max(20,(height*28+971)//972)
    clock=round((width+160)*(height+blank)*fps/10000)
    if not 1<=clock<=65535 or clock*10000>max_clock*1000000:
        raise ValueError('Pixel-clock ceiling exceeded; choose a lower refresh rate')
    return timing(clock,(width,width+48,width+80,width+160),(height,height+3,height+13,height+blank))


def finish(block):
    if len(block)>127:raise ValueError('EDID block overflow')
    block=bytearray(block);block.extend(bytes(127-len(block)));block.append(-sum(block)%256)
    return bytes(block)


def generate(modes,max_clock=165):
    if not 1<=len(modes)<=32 or not 1<=max_clock<=655:
        raise ValueError('Supply 1..32 modes and a valid pixel-clock ceiling')
    detailed=[reduced(*mode,max_clock) for mode in modes]
    base=bytearray.fromhex('00 ff ff ff ff ff ff 00 6b 56 02 00 00 00 00 00 00 24 01 03 80 00 00 78 06 00 00 00 00 00 00 00 00 00 00 00 00 00 01 01 01 01 01 01 01 01 01 01 01 01 01 01 01 01')
    assert len(base)==54
    for index in range(3):
        base+=detailed[index] if index<len(detailed) else bytes(18)
    base+=b'\x00\x00\x00\xfc\x00Virtual\n     '
    blocks=[bytearray((2,3,4,0))+b''.join(detailed[i:i+6]) for i in range(3,len(detailed),6)]
    base.append(len(blocks));assert len(base)==127
    return finish(base)+b''.join(finish(b) for b in blocks)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',action='append',required=True,help='WIDTHxHEIGHT@FPS; first is preferred')
    p.add_argument('--max-clock-mhz',type=int,default=165)
    args=p.parse_args()
    try:
        modes=[]
        for mode in args.mode:
            size,fps=mode.split('@');w,h=size.split('x');modes.append((int(w),int(h),int(fps)))
        data=generate(modes,args.max_clock_mhz)
    except (ValueError,OverflowError) as e:p.error(str(e))
    sys.stdout.buffer.write(data)


if __name__=='__main__':main()
