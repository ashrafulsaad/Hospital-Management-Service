from django.test import TestCase

# Create your tests here.
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_check():
    from django.test import Client

    client = Client()
    response = client.get('/api/health/')

    assert response.status_code == 200
    assert response.json()['status'] == 'healthy'
    assert response.json()['database'] == 'connected'
