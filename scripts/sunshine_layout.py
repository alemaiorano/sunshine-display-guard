"""Pure layout validation shared by the policy, session hooks and tests."""
import json
import math
import os
from pathlib import Path
import tempfile



def exclusive_output(layout, connector):
    """A single logical group is not necessarily a single physical output."""
    return (len(layout) == 1 and len(layout[0][-1]) == 1 and
            layout[0][-1][0][0] == connector)

def atomic_json(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def mode_candidates(modes):
    return [m for m in modes if m[5] and '+vrr' not in m[0]]


def choose_mode(modes, size=None, fps=60):
    modes = mode_candidates(modes)
    if not modes:
        raise ValueError('No usable display mode')
    if size is None:
        return next((m for m in modes if m[-1].get('is-preferred')), modes[0])
    w, h = size
    if w <= 0 or h <= 0 or not math.isfinite(fps) or fps <= 0:
        raise ValueError('Invalid client dimensions or refresh rate')
    # Exact aspect first, then resolution, then refresh. Prefer an exact mode.
    return min(modes, key=lambda m: (round(abs(math.log((m[1] / m[2]) / (w / h))), 5),
                                     abs(math.log((m[1] * m[2]) / (w * h))), abs(m[3] - fps)))


def layout_modes(modes):
    return [m for m in modes if m[5]]


def normalize_layout(layout, modes, exclude=None, layout_mode=1):
    """Repair stale primaries/coordinates/modes, preserving mirror groups and rotation.

    Disconnected members are removed. Invalid structure or incompatible mirrors
    are rejected; the caller can fall back to one physical screen.
    """
    rows, seen, rectangles = [], set(), []
    for row in layout:
        if len(row) != 6:
            raise ValueError('Invalid logical monitor')
        x, y, scale, transform, primary, members = row
        if (not isinstance(transform, int) or transform not in range(8)
                or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0
                or any(not isinstance(v, (int, float)) or not math.isfinite(v) or int(v) != v for v in (x, y))):
            raise ValueError('Invalid layout geometry')
        selected = []
        for connector, mode_id, props in members:
            if connector == exclude or connector not in modes:
                continue
            if connector in seen:
                raise ValueError('Repeated connector')
            seen.add(connector)
            available = layout_modes(modes[connector])
            current = next((m for m in available if m[0] == mode_id), None)
            if current is None:
                try:
                    current = choose_mode(available)
                except ValueError:
                    if not available:
                        raise
                    current = available[0]
            selected.append((connector, current, props))
        if not selected:
            continue
        # Mirrored outputs must share dimensions and an available scale.
        common_sizes = set.intersection(*(set((m[1], m[2]) for m in layout_modes(modes[c]))
                                          for c, _, _ in selected))
        if not common_sizes:
            raise ValueError('No common mode for mirrored outputs')
        desired = (selected[0][1][1], selected[0][1][2])
        if len(selected) > 1:
            size = min(common_sizes, key=lambda s: abs(math.log(s[0]/desired[0])) + abs(math.log(s[1]/desired[1])))
            selected = [(c, min((m for m in layout_modes(modes[c]) if (m[1],m[2]) == size),
                                  key=lambda m: (m[0] != old[0], abs(m[3]-old[3]))), p) for c,old,p in selected]
        scales = set.intersection(*(set(m[5]) for _, m, _ in selected))
        if not scales:
            raise ValueError('No common scale')
        scale = min(scales, key=lambda v: abs(v-scale))
        w, h = selected[0][1][1:3]
        if transform % 2:
            w, h = h, w
        factor = scale if layout_mode == 1 else 1.
        rectangles.append((int(x), int(y), round(w/factor), round(h/factor)))
        rows.append((int(x), int(y), float(scale), transform, bool(primary),
                     [(c, m[0], dict(p)) for c, m, p in selected]))
    if not rows:
        return []
    primary_index = next((i for i,r in enumerate(rows) if r[4]), 0)
    # Removal of a screen can leave a gap/overlap. Preserve valid arrangements;
    # otherwise pack the remaining screens horizontally without changing rotation.
    def touches(a,b):
        x,y,w,h=a; xx,yy,ww,hh=b
        return (((x+w==xx or xx+ww==x) and max(y,yy)<min(y+h,yy+hh)) or
                ((y+h==yy or yy+hh==y) and max(x,xx)<min(x+w,xx+ww)))
    overlap = any(max(a[0],b[0])<min(a[0]+a[2],b[0]+b[2]) and
                  max(a[1],b[1])<min(a[1]+a[3],b[1]+b[3])
                  for i,a in enumerate(rectangles) for b in rectangles[i+1:])
    connected={0}
    while True:
        expanded=connected | {i for i,a in enumerate(rectangles) if any(touches(a,rectangles[j]) for j in connected)}
        if expanded==connected: break
        connected=expanded
    pack=overlap or len(connected)!=len(rows)
    minx=min(r[0] for r in rows); miny=min(r[1] for r in rows)
    result=[]; offset=0
    for i,row in enumerate(rows):
        x,y,scale,transform,_,members=row
        result.append((offset if pack else x-minx, 0 if pack else y-miny,
                       scale,transform,i==primary_index,members))
        offset+=rectangles[i][2]
    return result
