from src.playerok_client import sale_from_deal_node
from src.playerok_graphql import edges, money


def test_edges_and_money():
    assert edges(None) == []
    assert edges({"edges": [{"node": {"id": "1"}}, {"node": None}]}) == [{"id": "1"}]
    assert money({"value": 199}) == 199.0
    assert money("12.5") == 12.5


def test_sale_from_deal_node():
    sale = sale_from_deal_node(
        {
            "id": "deal-1",
            "status": "PAID",
            "item": {"id": "item-9", "name": "Steam 500", "price": 450},
            "chat": {"id": "chat-3"},
            "user": {"id": "buyer-7"},
        }
    )
    assert sale is not None
    assert sale.id == "deal-1"
    assert sale.lot_id == "item-9"
    assert sale.title == "Steam 500"
    assert sale.price == 450.0
    assert sale.chat_id == "chat-3"
    assert sale.buyer_id == "buyer-7"
    assert sale.status == "paid"
