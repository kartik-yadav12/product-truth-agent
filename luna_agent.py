import json, os
from dotenv import load_dotenv
from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.inference.models import SystemMessage, UserMessage
load_dotenv()

class LunaAgent:
    def __init__(self):
        self.endpoint=os.getenv('CIS_LLM_ENDPOINT','https://llm-api-cis.azure-intlsd-np.nielsencsp.net/')
        self.key=os.getenv('CIS_LLM_API_KEY','')
        self.model=os.getenv('CIS_LLM_MODEL','hack-fest-gpt-5.6-luna')
        self.client=ChatCompletionsClient(endpoint=self.endpoint,credential=AzureKeyCredential(self.key),api_version='2025-03-01-preview') if self.key else None

    def predict(self, product, taxonomy_context, evidence):
        if not self.client: raise RuntimeError('CIS_LLM_API_KEY is not configured. Copy .env.example to .env and add your Bearer key.')
        system='''You are Product Truth Agent. Use ONLY supplied product evidence and the supplied taxonomy/guidelines. Do not invent facts. For each applicable characteristic, select an allowed value. If evidence is absent and the guideline defines a default, use that default. Return JSON only.'''
        payload={'product':product,'taxonomy':taxonomy_context,'evidence':evidence}
        user='''Classify this product. Return exactly this JSON shape:\n{"module":"...","characteristics":{"CHARACTERISTIC":"VALUE"},"product_url":"...","reasoning":"...","evidence":[{"claim":"...","source_url":"...","support":"supported|not_supported|unclear"}]}\nDo not output markdown.\nINPUT:\n'''+json.dumps(payload,ensure_ascii=False,default=str)
        res=self.client.complete(messages=[SystemMessage(content=system),UserMessage(content=user)],model=self.model,headers={'Authorization':self.key})
        raw=res.choices[0].message.content
        try: return json.loads(raw)
        except Exception:
            a=raw.find('{'); b=raw.rfind('}')
            if a>=0 and b>a: return json.loads(raw[a:b+1])
            raise ValueError('Luna returned non-JSON output: '+raw[:1000])
