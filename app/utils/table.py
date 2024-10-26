from matplotlib.figure import Figure
import plotly.graph_objects as go
import pandas as pd
from app.constant import (
    TABLE_HEADER_FONT_SIZE,
    TABLE_HEADER_HEIGHT,
    TABLE_ROW_HEIGHT,
    TABLE_ROW_FONT_SIZE,
    TABLE_WIDTH,
)


def create_table(df: pd.DataFrame) -> Figure:
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
                    values=list(df.columns),
                    align="left",
                    height=TABLE_HEADER_HEIGHT,
                    font_size=TABLE_HEADER_FONT_SIZE,
                ),
                cells=dict(
                    values=df.transpose().values.tolist(),
                    align="left",
                    height=TABLE_ROW_HEIGHT,
                    font_size=TABLE_ROW_FONT_SIZE,
                ),
            )
        ],
    )
    table_height = TABLE_HEADER_HEIGHT + (TABLE_ROW_HEIGHT * len(df.index) * 1.8)
    fig.update_layout(
        width=TABLE_WIDTH,
        height=table_height,
        margin=dict(l=20, r=20, t=20, b=20),
    )
    return fig
