import pandas as pd


def export_dataframe(df: pd.DataFrame, out_path: str, ext: str) -> None:
    if ext == "csv":
        df.to_csv(out_path, index=False)
    else:
        df.to_excel(out_path, index=False)
