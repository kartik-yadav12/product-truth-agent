class Taxonomy:
    def __init__(self, dataset): self.ds = dataset
    def get(self, module):
        rows = self.ds.characteristics_for_module(module)
        for r in rows:
            r['guideline'] = self.ds.guideline_for(module, r['characteristic'])
        return rows
    def validate(self, module, predictions):
        defs = {x['characteristic']: x for x in self.get(module)}
        errors=[]
        for k,v in predictions.items():
            if k not in defs: errors.append(f'{k}: characteristic not allowed for module')
            elif defs[k]['open_close'].strip().lower() == 'close' and v not in defs[k]['possible_values']:
                errors.append(f'{k}: {v!r} not in {defs[k]["possible_values"]}')
        return errors
