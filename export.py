import json, pandas as pd
from .data_loader import Dataset

def export_jsonl(path='outputs/dev_predictions.jsonl', out='outputs/predictions.xlsx'):
    ds=Dataset(); rows=[]
    with open(path,encoding='utf8') as f:
        for line in f:
            x=json.loads(line); rows.append(x)
    records=[]
    for x in rows:
        if x.get('prediction') is None: continue
        i=x['row']; base=ds.dev.iloc[i].to_dict(); p=x['prediction']
        base['PRODUCT_URL']=p.get('product_url',''); base['REASONING']=p.get('reasoning',''); base['MODULE']=p.get('module',base.get('MODULE',''))
        for k,v in p.get('characteristics',{}).items(): base[k]=v
        records.append(base)
    cols=list(ds.sample.columns)
    pd.DataFrame(records).reindex(columns=cols).to_excel(out,index=False)
    return out
