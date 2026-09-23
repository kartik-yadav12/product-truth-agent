from .data_loader import Dataset
from .retrieval import retrieve_product
from .luna_agent import LunaAgent
from .validator import validate


class ProductTruthPipeline:
    def __init__(self, dataset_path=None):
        self.ds = Dataset(dataset_path) if dataset_path else Dataset()

    def run(self, row, do_web=True):
        module = str(row.get('MODULE', '')).strip()

        if not module:
            raise ValueError(
                'MODULE is required for V1. For QA, use the module discovery stage in V2.'
            )

        ctx = self.ds.context(module)
        evidence = []

        if do_web:
            candidates = retrieve_product(row)

            print("\n=== RETRIEVAL RESULTS ===")
            for c in candidates[:4]:
                print("TITLE:", c.get("title"))
                print("URL:", c.get("url"))
                print("SCORE:", c.get("score"))
                print()

                p = c.get('page', {})

                evidence.append({
                    'title': c.get('title'),
                    'url': c.get('url'),
                    'snippet': c.get('snippet'),
                    'score': c.get('score'),
                    'page_text': p.get('text', '')
                })

        product = row.to_dict() if hasattr(row, 'to_dict') else row

        agent = LunaAgent()
        pred = agent.predict(product, ctx, evidence)

        print("\n=== LUNA OUTPUT ===")
        print(pred)

        clean, errors = validate(pred, ctx)

        pred['characteristics'] = clean
        pred['validation_errors'] = errors

        return pred, evidence