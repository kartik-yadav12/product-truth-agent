"""Streamlit UI for the Product Truth Agent."""

import pandas as pd
import streamlit as st

from src.data_loader import Dataset
from src.pipeline import ProductTruthPipeline

st.set_page_config(page_title="Product Truth Agent", layout="wide")
st.title("Product Truth Agent")
st.caption(
    "Dataset-grounded product identification, evidence extraction "
    "and characteristic coding"
)


@st.cache_resource
def get_dataset():
    return Dataset()


@st.cache_resource
def get_pipeline(offline: bool):
    # Shares the cached Dataset so the workbook is not re-read on every rerun.
    return ProductTruthPipeline(dataset=get_dataset(), offline=offline)


try:
    dataset = get_dataset()
except Exception as exc:  # noqa: BLE001 - surface setup errors in the UI
    st.error(f"Could not load the dataset: {exc}")
    st.stop()

mode = st.sidebar.radio("Mode", ["Development product", "Custom product"])
use_web = st.sidebar.checkbox("Web retrieval", value=True)
offline = st.sidebar.checkbox(
    "Offline baseline agent", value=False, help="Skip the LLM and use the deterministic agent"
)

if mode == "Development product":
    index = st.sidebar.number_input(
        "dev row", min_value=0, max_value=len(dataset.dev) - 1, value=0
    )
    row = dataset.dev.iloc[int(index)].to_dict()
    st.write("**Product:**", row["RETAILER_DESC"])
    st.write("**Brand:**", row["BRAND"])
    st.write("**Module:**", row["MODULE"])
else:
    row = {
        "ITEM_CODE": st.text_input("ITEM_CODE"),
        "EXTERNAL_CODE": st.text_input("Barcode / EXTERNAL_CODE"),
        "BRAND": st.text_input("Brand"),
        "RETAILER_DESC": st.text_input("Retailer description"),
        "COUNTRY": st.text_input("Country", "GB"),
        "MODULE": st.selectbox("Module", dataset.modules()),
    }

if st.button("Run Product Truth Agent", type="primary"):
    with st.spinner("Retrieving evidence and classifying..."):
        try:
            pipeline = get_pipeline(offline)
            prediction, evidence = pipeline.run(row, do_web=use_web)
        except Exception as exc:  # noqa: BLE001 - surface runtime errors in the UI
            st.error(str(exc))
        else:
            st.subheader(f"Prediction (agent: {prediction.get('agent')})")

            characteristics = prediction.get("characteristics") or {}
            if characteristics:
                st.dataframe(
                    pd.DataFrame(
                        sorted(characteristics.items()),
                        columns=["Characteristic", "Value"],
                    ),
                    width="stretch",
                )
            else:
                st.warning("No characteristics survived validation.")

            st.write("**Product URL:**", prediction.get("product_url") or "-")
            st.write("**Reasoning:**", prediction.get("reasoning") or "-")

            for label, key in (
                ("Validation errors", "validation_errors"),
                ("Validation warnings", "validation_warnings"),
            ):
                items = prediction.get(key) or []
                if items:
                    with st.expander(f"{label} ({len(items)})"):
                        for item in items:
                            st.write("-", item)

            st.subheader(f"Evidence ({len(evidence)})")
            if evidence:
                st.dataframe(
                    pd.DataFrame(evidence)[
                        ["score", "domain", "title", "url", "snippet"]
                    ],
                    width="stretch",
                )
            else:
                st.info("No evidence retrieved.")

            with st.expander("Raw prediction JSON"):
                st.json(prediction)
