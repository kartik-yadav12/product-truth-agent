from pathlib import Path
import ast
import pandas as pd

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / 'data' / 'product_truth_agent_dataset.xlsx'

class Dataset:
    def __init__(self, path=DEFAULT_DATASET):
        self.path = Path(path)
        self.dev = pd.read_excel(self.path, sheet_name='dev').fillna('')
        self.qa = pd.read_excel(self.path, sheet_name='qa').fillna('')
        self.values = pd.read_excel(self.path, sheet_name='char_value_list').fillna('')
        self.guidelines = pd.read_excel(self.path, sheet_name='char_guidelines').fillna('')
        self.sample = pd.read_excel(self.path, sheet_name='sample_output').fillna('')
        self.guide = pd.read_excel(self.path, sheet_name='dataset_understanding_guide').fillna('')

    @staticmethod
    def parse_values(x):
        if isinstance(x, list): return x
        try: return ast.literal_eval(str(x))
        except Exception: return [v.strip() for v in str(x).split('|') if v.strip()]

    def taxonomy_for_module(self, module):
        rows = self.values[self.values['module'].astype(str).str.strip() == str(module).strip()]
        out=[]
        for _, r in rows.iterrows():
            out.append({'characteristic': str(r['characteristic']), 'open_close': str(r['open_close']),
                        'binary': str(r['binary']), 'possible_values': self.parse_values(r['possible_values']),
                        'notes': str(r['Notes'])})
        return out

    def guidelines_for_module(self, module):
        rows = self.guidelines[self.guidelines['MODULE NAME'].astype(str).str.strip() == str(module).strip()]
        return [{'characteristic': str(r['CHARACTERISTICS NAME']), 'guideline': str(r['Guidelines'])} for _,r in rows.iterrows()]

    def module_examples(self, module, n=5):
        rows = self.dev[self.dev['MODULE'].astype(str).str.strip() == str(module).strip()].head(n)
        return rows.to_dict('records')

    def context(self, module, examples=4):
        return {'module': module, 'characteristics': self.taxonomy_for_module(module),
                'guidelines': self.guidelines_for_module(module), 'examples': self.module_examples(module, examples)}
