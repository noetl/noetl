"""
Tests for common Pydantic utilities in noetl.core.common.

Tests AppBaseModel, transform function, and related utilities.
"""

import pytest
from pydantic import BaseModel, ValidationError
from noetl.core.common import AppBaseModel, transform
from noetl.core import AppBaseModel as CoreAppBaseModel, transform as core_transform


class TestAppBaseModel:
    """Test AppBaseModel base class."""
    
    def test_app_base_model_exists(self):
        """Test that AppBaseModel is importable."""
        assert AppBaseModel is not None
        assert issubclass(AppBaseModel, BaseModel)
    
    def test_app_base_model_config(self):
        """Test that AppBaseModel has correct configuration."""
        config = AppBaseModel.model_config
        assert config['from_attributes'] is True
        assert config['coerce_numbers_to_str'] is True
    
    def test_inheritance(self):
        """Test that models can inherit from AppBaseModel."""
        class TestModel(AppBaseModel):
            name: str
            value: int
        
        assert issubclass(TestModel, AppBaseModel)
        assert issubclass(TestModel, BaseModel)
    
    def test_from_attributes_support(self):
        """Test ORM mode support (from_attributes)."""
        class TestModel(AppBaseModel):
            name: str
            count: int
        
        # Simulate ORM object with attributes
        class FakeORMObject:
            def __init__(self):
                self.name = "test"
                self.count = 42
        
        orm_obj = FakeORMObject()
        model = TestModel.model_validate(orm_obj)
        
        assert model.name == "test"
        assert model.count == 42
    
    def test_coerce_numbers_to_str(self):
        """Test automatic number to string coercion."""
        class TestModel(AppBaseModel):
            id: str
            name: str
        
        # Should accept integer and coerce to string
        model = TestModel(id=12345, name="test")
        assert model.id == "12345"
        assert isinstance(model.id, str)
        
        # Should also accept string directly
        model2 = TestModel(id="67890", name="test")
        assert model2.id == "67890"
    
    def test_snowflake_id_handling(self):
        """Test handling of large Snowflake IDs."""
        class TestModel(AppBaseModel):
            catalog_id: str
            execution_id: str
        
        # Large Snowflake ID
        snowflake_id = 477853774095056942
        
        model = TestModel(
            catalog_id=snowflake_id,
            execution_id=str(snowflake_id)
        )
        
        assert model.catalog_id == str(snowflake_id)
        assert model.execution_id == str(snowflake_id)
        assert isinstance(model.catalog_id, str)
        assert isinstance(model.execution_id, str)


class TestTransformFunction:
    """Test transform utility function."""
    
    def test_transform_basic(self):
        """Test basic dict to model transformation."""
        class TestModel(BaseModel):
            name: str
            value: int
        
        data = {'name': 'test', 'value': 123}
        result = transform(TestModel, data)
        
        assert isinstance(result, TestModel)
        assert result.name == 'test'
        assert result.value == 123
    
    def test_transform_with_app_base_model(self):
        """Test transform with AppBaseModel."""
        class TestModel(AppBaseModel):
            id: str
            count: int
        
        data = {'id': 12345, 'count': 100}
        result = transform(TestModel, data)
        
        assert isinstance(result, TestModel)
        assert result.id == "12345"  # Coerced to string
        assert result.count == 100
    
    def test_transform_validation_error(self):
        """Test that transform raises ValidationError for invalid data."""
        class TestModel(BaseModel):
            name: str
            value: int
        
        # Invalid data - value should be int
        data = {'name': 'test', 'value': 'not_an_int'}
        
        with pytest.raises(ValidationError) as exc_info:
            transform(TestModel, data)
        
        # Check that error is logged (validation error raised)
        assert exc_info.value is not None
    
    def test_transform_missing_required_field(self):
        """Test transform with missing required field."""
        class TestModel(BaseModel):
            name: str
            value: int
        
        # Missing 'value' field
        data = {'name': 'test'}
        
        with pytest.raises(ValidationError):
            transform(TestModel, data)
    
    def test_transform_extra_fields_ignored(self):
        """Test that extra fields are handled according to model config."""
        class TestModel(BaseModel):
            name: str
        
        # Extra field 'extra' should be ignored by default
        data = {'name': 'test', 'extra': 'ignored'}
        result = transform(TestModel, data)
        
        assert result.name == 'test'
        assert not hasattr(result, 'extra')


class TestImportPaths:
    """Test that imports work from different paths."""
    
    def test_import_from_core_common(self):
        """Test import from noetl.core.common."""
        from noetl.core.common import AppBaseModel as Common1, transform as transform1
        
        assert Common1 is not None
        assert transform1 is not None
    
    def test_import_from_core_package(self):
        """Test import from noetl.core package root."""
        assert CoreAppBaseModel is not None
        assert core_transform is not None
    
    def test_same_objects(self):
        """Test that both import paths reference same objects."""
        assert AppBaseModel is CoreAppBaseModel
        assert transform is core_transform
    
    def test_catalog_models_available(self):
        """Test that catalog models can be imported."""
        from noetl.server.api.catalog import CatalogEntry, CatalogResource
        
        assert CatalogEntry is not None
        assert CatalogResource is not None
        assert issubclass(CatalogEntry, AppBaseModel)
        assert issubclass(CatalogResource, AppBaseModel)


class TestRealWorldUsage:
    """Test real-world usage scenarios."""
    
    def test_catalog_entry_like_model(self):
        """Test model similar to CatalogEntry."""
        class CatalogEntry(AppBaseModel):
            path: str
            version: str
            content: str
            catalog_id: str
        
        data = {
            'path': 'examples/data_transfer/http_to_postgres',
            'version': 3,  # Integer version
            'content': 'apiVersion: noetl.io/v1...',
            'catalog_id': 477853774095056942  # Large int
        }
        
        entry = transform(CatalogEntry, data)
        
        assert entry.path == 'examples/data_transfer/http_to_postgres'
        assert entry.version == '3'  # Coerced to string
        assert entry.catalog_id == '477853774095056942'  # Coerced to string
    
    def test_resource_content_like_model(self):
        """Test model similar to CatalogResource."""
        class CatalogResource(AppBaseModel):
            catalog_id: str
            path: str
            version: int
            kind: str
            content: str
        
        # Simulate database row
        class DBRow:
            def __init__(self):
                self.catalog_id = 12345
                self.path = 'test/path'
                self.version = 1
                self.kind = 'Playbook'
                self.content = 'content'
        
        row = DBRow()
        resource = CatalogResource.model_validate(row)
        
        assert resource.catalog_id == '12345'  # Coerced to string
        assert resource.path == 'test/path'
        assert resource.version == 1
        assert resource.kind == 'Playbook'
        assert resource.content == 'content'
    
    def test_multiple_models_consistency(self):
        """Test that multiple models using AppBaseModel behave consistently."""
        class Model1(AppBaseModel):
            id: str
            
        class Model2(AppBaseModel):
            id: str
        
        # Both should coerce the same way
        m1 = Model1(id=123)
        m2 = Model2(id=123)
        
        assert m1.id == m2.id == "123"
        assert type(m1.id) == type(m2.id) == str


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_none_handling(self):
        """Test handling of None values."""
        class TestModel(AppBaseModel):
            name: str
            optional: str | None = None
        
        model = TestModel(name="test", optional=None)
        assert model.name == "test"
        assert model.optional is None
    
    def test_empty_string_coercion(self):
        """Test empty string handling."""
        class TestModel(AppBaseModel):
            value: str
        
        model = TestModel(value="")
        assert model.value == ""
    
    def test_zero_coercion(self):
        """Test that zero is properly coerced."""
        class TestModel(AppBaseModel):
            count: str
        
        model = TestModel(count=0)
        assert model.count == "0"
        assert isinstance(model.count, str)
    
    def test_negative_number_coercion(self):
        """Test negative number coercion."""
        class TestModel(AppBaseModel):
            balance: str
        
        model = TestModel(balance=-100)
        assert model.balance == "-100"
    
    def test_float_coercion(self):
        """Test float to string coercion."""
        class TestModel(AppBaseModel):
            amount: str
        
        model = TestModel(amount=123.45)
        assert model.amount == "123.45"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
