"""Unit: parsers extract routes/models/functions/components."""
from app.analysis.structural.parsers import parse_python, parse_js_ts

PY = '''
from fastapi import APIRouter
router = APIRouter()
class Order(Base):
    status = Column(String)
@router.post("/orders")
def create_order(order_id: int):
    """Create."""
    if order.status == "approved":
        raise ValueError("locked")
    return order
'''

JS = '''
export default function CartPage() { return null; }
app.post('/api/checkout', handler);
const data = await fetch('/api/orders');
'''


def test_python_parser():
    syms = parse_python(PY)
    kinds = {(s.kind, s.name) for s in syms}
    assert ("route", "POST /orders") in kinds
    assert ("model", "Order") in kinds
    assert any(k == "function" and n == "create_order" for k, n in kinds)


def test_js_parser():
    syms = parse_js_ts(JS)
    assert any(s.kind == "component" and s.name == "CartPage" for s in syms)
    assert any(s.kind == "route" for s in syms)
