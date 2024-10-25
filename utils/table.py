from matplotlib.figure import Figure
import plotly.graph_objects as go
import pandas as pd


def create_table(df: pd.DataFrame, height=300) -> Figure:
    """Create table from dataframe.

    Args:
        df (pd.DataFrame): dataframe containing columns and values.

    Returns:
        Figure: figure representing table.
    """
    fig = go.Figure(
        layout=go.Layout(autosize=True),
        data=[
            go.Table(
                header=dict(
                    values=list(df.columns), align="left", height=30, font_size=15
                ),
                cells=dict(
                    values=df.transpose().values.tolist(),
                    align="left",
                    height=40,
                    font_size=14,
                ),
            )
        ],
    )
    fig.update_layout(
        width=1000,
        height=height,
        margin=dict(l=20, r=20, t=20, b=20),
    )
    return fig
