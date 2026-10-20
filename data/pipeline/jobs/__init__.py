"""One module per source family; each job returns rows that carry full provenance."""
from ..fetch import SourceUnavailable


def need(ctx: dict, key: str, job: str):
    """Value an upstream job put in ctx; a missing one makes this job unavailable rather than silently empty."""
    if key not in ctx:
        raise SourceUnavailable(f'needs {job}, which is unavailable')
    return ctx[key]


def prov(meta: dict, as_of: str, retrieved: str) -> dict:
    return {'source': meta['source'], 'as_of': as_of, 'confidence': meta['confidence'], 'license': meta['license'], 'retrieved': retrieved}
