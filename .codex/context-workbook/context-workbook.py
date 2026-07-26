import marimo

__generated_with = "0.23.14"
app = marimo.App(width="full")


@app.cell
def _():
    import json

    import marimo as mo

    return json, mo


@app.cell
def _():
    # The graph service is the sole evaluator.  Browserless callers inject its
    # canonical result; the workbook only renders that immutable projection.
    graph_service_result = None
    return (graph_service_result,)


@app.cell
def _(graph_service_result):
    workbook_result = graph_service_result
    return (workbook_result,)


@app.cell
def _(mo, workbook_result):
    mo.vstack(
        [
            mo.md("# Authoritative context graph service"),
            mo.md("This workbook displays the supplied service result without recalculation."),
            mo.json(workbook_result),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
