"""Pass backend scalar outputs through as metric outputs."""
from bplsim.metrics import metric


@metric(version="1.0.0", inputs={"data": "scalars"}, outputs="*")
def scalar(data):
    return {k: float(v) for k, v in data.fields.items()}
