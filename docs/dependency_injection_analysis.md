# Dependency Injection in NoETL API Services

**Question**: Do we need to use FastAPI dependency injection for `RuntimeService` and `ExecutionService` to avoid memory leaks?

**Short Answer**: **No, dependency injection is not needed** for our current architecture. Our services are stateless with static methods, so there's no memory leakage risk.

## Current Architecture Analysis

### Our Service Pattern
```python
class RuntimeService:
    """Stateless service with only static methods."""
    
    @staticmethod
    async def register_component(request: Request) -> Response:
        # No instance state
        # Creates and releases resources within method scope
        async with get_async_db_connection() as conn:
            # Database operations
            ...
        return response
```

### Usage in Endpoints
```python
from .service import RuntimeService

@router.post("/endpoint")
async def endpoint(request: Request):
    return await RuntimeService.register_component(request)
```

## Why Dependency Injection is NOT Needed

### 1. Stateless Services
- All service methods are `@staticmethod`
- No instance variables or shared state
- No object lifecycle to manage
- No memory accumulation between requests

### 2. Proper Resource Management
- Database connections created and released per method call
- Async context managers ensure cleanup
- No connection pooling at service level
- Resources scoped to request lifetime

### 3. No Memory Leaks
Memory leaks occur when:
- Objects hold references that prevent garbage collection
- Resources aren't properly cleaned up
- State accumulates across requests

Our architecture avoids all these:
```python
# Each call is independent
await RuntimeService.method1(req)  # Creates/releases resources
await RuntimeService.method2(req)  # Creates/releases resources
# No shared state between calls
```

### 4. Import is Not Instantiation
```python
from .service import RuntimeService  # Imports the class
RuntimeService.method()  # Calls static method, no instance created
```

This is different from:
```python
service = RuntimeService()  # Would create instance (if we had __init__)
service.method()  # Would call instance method
```

## When Dependency Injection IS Useful

Dependency injection would be beneficial for:

### 1. Stateful Services
```python
class StatefulService:
    def __init__(self, db_pool, cache, config):
        self.db_pool = db_pool
        self.cache = cache
        self.config = config
    
    async def method(self):
        # Uses instance state
        await self.db_pool.execute(...)
```

### 2. Multiple Implementations
```python
class RuntimeServiceInterface(ABC):
    @abstractmethod
    async def register_component(self, request): ...

class RuntimeServiceV1(RuntimeServiceInterface): ...
class RuntimeServiceV2(RuntimeServiceInterface): ...

# Inject different implementations
def get_service() -> RuntimeServiceInterface:
    if feature_flag_enabled():
        return RuntimeServiceV2()
    return RuntimeServiceV1()
```

### 3. Testing with Mocks
```python
# With DI, easy to mock
def get_service():
    return RuntimeService()

# In tests
async def test_endpoint(mock_service):
    app.dependency_overrides[get_service] = lambda: mock_service
```

### 4. Shared Resources
```python
# Database pool shared across requests
async def get_db_pool():
    return app.state.db_pool

@router.get("/endpoint")
async def endpoint(pool: Annotated[Pool, Depends(get_db_pool)]):
    async with pool.connection() as conn:
        ...
```

## When to Use Dependency Injection in NoETL

We SHOULD use dependency injection for:

### 1. Database Connections ✅ (Already doing this)
```python
async def get_db():
    async with get_async_db_connection() as conn:
        yield conn

@router.get("/endpoint")
async def endpoint(db: Annotated[Connection, Depends(get_db)]):
    # Connection managed by dependency system
    await db.execute(...)
```

### 2. Configuration ✅ (Consider for future)
```python
def get_settings() -> Settings:
    return Settings()

@router.get("/endpoint")
async def endpoint(settings: Annotated[Settings, Depends(get_settings)]):
    # Easy to mock in tests
    ...
```

### 3. External Services (Consider for future)
```python
async def get_http_client():
    async with httpx.AsyncClient() as client:
        yield client

@router.get("/endpoint")
async def endpoint(client: Annotated[httpx.AsyncClient, Depends(get_http_client)]):
    # Client lifecycle managed
    ...
```

## Current Architecture is Optimal

For NoETL's service pattern, the current approach is optimal because:

### Advantages of Current Approach:
1. **Simplicity**: No dependency boilerplate needed
2. **Clarity**: Direct method calls are easy to understand
3. **Performance**: No dependency resolution overhead
4. **Type Safety**: Full IDE autocomplete and type checking
5. **Zero Memory Overhead**: No dependency injection framework overhead

### What We're Already Doing Right:
```python
# ✅ Proper resource management
async with get_async_db_connection() as conn:
    # Connection created, used, and released

# ✅ No shared state
@staticmethod
async def method():
    # All state is local to method

# ✅ Exception safety
try:
    async with resource:
        ...
except Exception:
    # Resource cleaned up automatically
```

## If You Want to Add Dependency Injection Anyway

If you prefer the dependency injection pattern for consistency or testing, here's how:

```python
# service.py
class RuntimeService:
    """Keep existing static methods."""
    
    @staticmethod
    async def register_component(...): ...
    
    # Or convert to instance methods if you need state later
    async def register_component(self, ...): ...

# endpoint.py
from typing import Annotated
from fastapi import Depends

def get_runtime_service() -> RuntimeService:
    """
    Dependency factory.
    
    Since service is stateless, we can:
    1. Return the class itself for static methods
    2. Return a new instance each time (no overhead if stateless)
    3. Return a singleton instance
    """
    return RuntimeService  # For static methods
    # OR
    # return RuntimeService()  # For instance methods

@router.post("/endpoint")
async def endpoint(
    request: Request,
    service: Annotated[RuntimeService, Depends(get_runtime_service)]
):
    return await service.register_component(request)
```

### Testing with Dependency Injection:
```python
# test_endpoint.py
from unittest.mock import AsyncMock

async def test_register_endpoint():
    mock_service = AsyncMock()
    mock_service.register_component.return_value = Response(...)
    
    app.dependency_overrides[get_runtime_service] = lambda: mock_service
    
    response = client.post("/endpoint", json={...})
    assert response.status_code == 200
```

## Recommendation

**For NoETL's current architecture:**

✅ **Keep the current approach** - It's clean, simple, and has zero memory leak risk

**Consider dependency injection if you:**
- Need to add stateful services in the future
- Want to implement multiple service versions
- Need easier mocking in tests (though you can mock imported classes too)
- Want to manage shared resource pools at the application level

**But remember:**
- Current approach has **no memory leak risk**
- Dependency injection adds complexity
- Our services are already properly scoped
- Resources are correctly managed with async context managers

## Memory Leak Prevention Checklist

✅ Use async context managers for resources  
✅ No global mutable state  
✅ No instance variables in service classes  
✅ Database connections scoped to request/method  
✅ Exceptions properly handled with cleanup  
✅ No circular references  
✅ No unbounded caches or collections  

Our codebase already follows all these practices, so **no changes needed** to prevent memory leaks.

---

**Conclusion**: The current architecture is solid. Dependency injection would be a refactoring exercise for testability, not a memory leak fix. If you want DI for testing purposes, it's a nice-to-have, not a must-have.
