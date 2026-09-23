import re

def norm(s): return re.sub(r'\s+',' ',str(s or '').strip()).upper()

def validate(pred, context):
    allowed={norm(x['characteristic']):[norm(v) for v in x['possible_values']] for x in context['characteristics']}
    fixed={norm(x['characteristic']):x for x in context['characteristics']}
    errors=[]; clean={}
    for k,v in (pred.get('characteristics') or {}).items():
        nk=norm(k); nv=norm(v)
        if nk not in allowed: errors.append(f'Unknown characteristic: {k}'); continue
        if fixed[nk]['open_close'].lower().startswith('close') and nv not in allowed[nk]:
            errors.append(f'Invalid closed value for {k}: {v}; allowed={fixed[nk]["possible_values"]}')
        clean[k]=v
    for c in context['characteristics']:
        if c['characteristic'] not in clean and c['characteristic'] not in [k.upper() for k in clean]:
            pass
    return clean, errors
