import streamlit as st, pandas as pd
from src.data_loader import Dataset
from src.pipeline import ProductTruthPipeline
st.set_page_config(page_title='Product Truth Agent',layout='wide')
st.title('🔎 Product Truth Agent')
st.caption('Dataset-grounded product identification, evidence extraction and characteristic coding')

@st.cache_resource
def get_ds(): return Dataset()
ds=get_ds(); pipe=ProductTruthPipeline()
mode=st.sidebar.radio('Mode',['Development product','Custom product'])
if mode=='Development product':
    idx=st.sidebar.number_input('dev row',min_value=0,max_value=len(ds.dev)-1,value=0)
    row=ds.dev.iloc[int(idx)]
    st.write('**Product:**',row['RETAILER_DESC']); st.write('**Module:**',row['MODULE'])
else:
    row={}
    row['ITEM_CODE']=st.text_input('ITEM_CODE'); row['EXTERNAL_CODE']=st.text_input('Barcode / EXTERNAL_CODE'); row['BRAND']=st.text_input('Brand'); row['RETAILER_DESC']=st.text_input('Retailer description'); row['COUNTRY']=st.text_input('Country','GB'); row['MODULE']=st.selectbox('Module',sorted([x for x in ds.values['module'].unique() if str(x).strip()]))
if st.button('Run Product Truth Agent',type='primary'):
    with st.spinner('Retrieving evidence and asking Luna...'):
        try:
            pred,evidence=pipe.run(row)
            st.subheader('Prediction'); st.json(pred)
            st.subheader('Evidence'); st.dataframe(pd.DataFrame(evidence),use_container_width=True)
        except Exception as e: st.error(str(e))
