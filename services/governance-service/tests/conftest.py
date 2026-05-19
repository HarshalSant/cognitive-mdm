import pytest
from datetime import datetime, timezone


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


@pytest.fixture
def sample_entity():
    return {
        "id": "e-001",
        "entity_type": "customer",
        "fields": {
            "name": "Acme Corporation",
            "email": "info@acme.com",
            "phone": "+1-312-555-0101",
            "address": "100 Main Street",
        },
        "source": "salesforce_crm",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
