import argparse, json, pandas as pd
from .data_loader import Dataset
from .pipeline import ProductTruthPipeline

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--limit',type=int,default=10); ap.add_argument('--web',action='store_true'); ap.add_argument('--out',default='outputs/dev_predictions.jsonl'); args=ap.parse_args()
    ds=Dataset(); pipe=ProductTruthPipeline(); rows=[]
    for i,row in ds.dev.head(args.limit).iterrows():
        try:
            pred,_=pipe.run(row,do_web=args.web); rows.append({'row':int(i),'prediction':pred,'error':''})
        except Exception as e: rows.append({'row':int(i),'prediction':None,'error':str(e)})
        print(f'[{i+1}/{min(args.limit,len(ds.dev))}] done')
    with open(args.out,'w',encoding='utf8') as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False,default=str)+'\n')
    print('Wrote',args.out)
if __name__=='__main__': main()
