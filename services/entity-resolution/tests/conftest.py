"""Shared test fixtures for entity-resolution service."""
import pytest


@pytest.fixture
def sample_customer():
    return {
        "id": "cust-001",
        "entity_type": "customer",
        "fields": {
            "name": "Acme Corporation",
            "email": "info@acme.com",
            "phone": "+1-312-555-0101",
            "address": "100 Main Street",
            "city": "Chicago",
            "country": "US",
        },
    }


@pytest.fixture
def duplicate_customer():
    return {
        "id": "cust-002",
        "entity_type": "customer",
        "fields": {
            "name": "ACME Corp",
            "email": "info@acme.com",
            "phone": "312-555-0101",
            "address": "100 Main St",
            "city": "Chicago",
            "country": "US",
        },
    }


@pytest.fixture
def unrelated_customer():
    return {
        "id": "cust-999",
        "entity_type": "customer",
        "fields": {
            "name": "Zeta Industries",
            "email": "contact@zeta.com",
            "phone": "+1-469-555-9999",
            "address": "500 Commerce Blvd",
            "city": "Dallas",
            "country": "US",
        },
    }
