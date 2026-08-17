from pydantic import BaseModel


class EquipmentCounts(BaseModel):
    durable: int
    material: int
    consumable: int
    total: int


class DashboardSummaryResponse(BaseModel):
    pending_requests: int
    overdue_requests: int
    low_stock_items: int
    active_borrows: int
    equipment_counts: EquipmentCounts
    consumed_value_this_month: float
