docker-compose up                    # Start all services
docker exec -it kaavapino-api bash   # Shell into API container
echo 'DEBUG=True' >> .env
# Kaavapino Copilot Instructions

## Scope & Guardrails
- Multiple services live here (`kaavapino` Django API, `kaavapino-ui` frontend, `kaavoitus-api` integrations, `kaavapino-pipelines`). Confirm the target service before editing and avoid cross-service edits unless the task explicitly spans them.
- When working on the API, always reuse the helpers in `projects/models/*.py`, `projects/serializers/`, and `projects/tasks.py` instead of writing ad-hoc logic. The dynamic `attribute_data` field must be mutated through `Project.update_attribute_data()`.
- Keep privilege checks (`users/models.py::User.has_privilege`) and async task triggers (Django-Q in `projects/tasks.py`) intact; call out any change that could affect permissions, migrations, or background processing.

## Architecture Map
- `kaavapino/` — Django REST API exposing `/v1` endpoints backed by PostgreSQL + PostGIS, Redis cache, and GeoDjango; pipelines under `deploy/` and Rancher scripts in `deploy/rancher/`.
- `kaavapino-ui/` — Vite/React SPA that edits the same project data; proxies API calls in dev and relies on OpenID + optional static API tokens for fake login.
- `kaavoitus-api/` — Django service that brokers data between Kaavapino, Facta (Oracle), and GeoServer; authentication is API-key based with credentials managed via `drf_ext_credentials` commands.
- `kaavapino-pipelines/` — Azure DevOps YAML definitions for API/UI builds, audit logging, OWASP ZAP, Redis, PgBouncer, and infra automation; edits here affect deployment gates.

## Backend Domain Patterns (`kaavapino/`)
- Central models: `projects/models/project.py`, `projects/models/attribute.py`, and phase/type definitions. Attributes declare value types, serialization, and validation; never bypass them.
- Imports & schedules: Excel-driven management commands (`projects/management/commands/`) load attributes, deadlines, list views, and report types. Deadlines depend on attributes—run `import_attributes` before `import_deadlines`.
- Async jobs use Django-Q (`projects/tasks.py`) for document exports, cache refreshes, and background calculations. Ensure new heavy work is scheduled rather than blocking HTTP requests.
- Testing is via `pytest` with factories in `projects/tests/factories.py`. Prefer `pytest -k` or module-level targets when scoping fixes.
- **Logging: Always use `log.info()` for debug/trace logging unless explicitly specified otherwise.** `log.debug()` is not visible in normal operation and should be avoided for troubleshooting.

## Backend Workflows
- Docker: `docker-compose up` brings up API + db; `docker exec -it kaavapino-api bash` drops you into the container for management commands.
- Manual: `poetry install && poetry shell`, add `DEBUG=True` to `.env`, run `python manage.py migrate` then `runserver 0.0.0.0:8000`. PostGIS must be enabled on both dev and test databases (`CREATE EXTENSION postgis`).
- Data fixing: `repair_attribute_data`, `clear_all_project_deadlines`, `generate_missing_project_deadlines`, and `create_default_groups_and_mappings` are the canonical tools for cleaning broken imports.
- Schema/docs: `./manage.py spectacular --file schema/schema.yaml` regenerates the OpenAPI spec surfaced at `/schema/swagger-ui/`.

## Frontend Workflows (`kaavapino-ui/`)
- Requires `.env` with `REACT_APP_OPENID_CONNECT_CLIENT_ID`, `REACT_APP_OPENID_ENDPOINT`, audience, environment, and optional `REACT_APP_API_TOKEN` for fake login.
- `yarn install` followed by `yarn start` runs the dev proxy against the local API; production builds go through Azure pipelines defined in `kaavapino-ui/azure-pipelines-*.yml`.
- Temporary fake login: create a Django superuser + API token inside the API container, then place the token in the frontend `.env` for local-only testing.

## Integration Service (`kaavoitus-api/`)
- Acts as a bridge between Kaavapino, Facta, and GeoServer; configure `.env` plus `config_dev.env` for logging and Oracle mocking.
- External credentials are stored via `./manage.py drf_ext_credentials` (SQLite in dev) and tied to API keys created with `drf_create_token`. Each key can selectively access Facta/GeoServer/Kaavapino.
- Mock Facta by pointing `FACTA_DB_MOCK_DATA_DIR` to `mock-data/` when Oracle connectivity is unavailable.

## Deployment & Pipelines
- Rancher scripts under `kaavapino/deploy/rancher/` and `kaavapino-ui/deploy/rancher/` handle staging deploys (`./deploy_staging_api.sh <version> run`, `./deploy_staging_web.sh web:<version> run`).
- Azure DevOps YAMLs in `kaavapino/azure-pipelines-*.yml`, `kaavapino-ui/azure-pipelines-*.yml`, and `kaavoitus-api/azure-pipelines-*.yml` define CI/CD; modifying Dockerfiles or dependencies likely requires syncing these pipelines.
- `kaavapino-pipelines/` centralizes shared infrastructure jobs (Redis, PgBouncer, audit logging, OWASP scanning). Touch with care and document any cross-pipeline impacts.

## When Stuck
- Cross-check expected behavior against `README.md` in each service root for canonical commands and deployment notes.
- If a required helper or config is missing, pause and confirm requirements with the user rather than guessing—this codebase relies on shared migrations and pipelines, and stray edits have organization-wide impact.
Content-Type: application/json
Authorization: Bearer <jwt_token>

{
    "attribute_data": {
        "status": "approved",
        "approval_date": "2025-12-19"
    }
}

Response 200:
{
    "id": 123,
    "name": "Kalasatama Block 15",
    "attribute_data": {
        "address": "Kalasatamankatu 5",
        "area_size": 8500,
        "project_manager": "jane.doe",
        "status": "approved",
        "approval_date": "2025-12-19"
    }
}
```

### Querying Projects with Filters
```http
GET /v1/projects/?phase=2&type=1&search=kalasatama
Authorization: Bearer <jwt_token>

Response 200:
{
    "count": 15,
    "next": "/v1/projects/?page=2&phase=2&type=1",
    "previous": null,
    "results": [...]
}
```

## Common Workflows

### Adding a New Attribute Type

1. **Define attribute in admin or Excel import:**
```python
python manage.py import_attributes attributes.xlsx
```

2. **Add to project phase section:**
```python
from projects.models import ProjectPhaseSectionAttribute

section = phase.sections.get(name="Basic Info")
attribute = Attribute.objects.get(identifier="new_field")

ProjectPhaseSectionAttribute.objects.create(
    section=section,
    attribute=attribute,
    index=10  # Display order
)
```

3. **Test serialization:**
```python
project.update_attribute_data({"new_field": "test value"})
deserialized = project.get_attribute_data()["new_field"]
```

### Creating a Custom API Endpoint

1. **Add view to projects/views.py:**
```python
from rest_framework.decorators import action
from rest_framework.response import Response

class ProjectViewSet(viewsets.ModelViewSet):
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        project = self.get_object()
        
        if not request.user.has_privilege(project, "admin"):
            raise PermissionDenied()
        
        project.update_attribute_data({
            "approval_status": "approved",
            "approved_by": request.user.username,
            "approved_at": datetime.now().isoformat()
        })
        project.save()
        
        return Response({"status": "approved"})
```

2. **Endpoint available at:**
```
POST /v1/projects/{id}/approve/
```

### Debugging Attribute Data Issues

```python
# Management command to repair broken attribute_data
python manage.py repair_attribute_data --id 123

# In code: validate attribute_data structure
from projects.models import Attribute

project = Project.objects.get(id=123)
for key, value in project.attribute_data.items():
    try:
        attr = Attribute.objects.get(identifier=key)
        # Test deserialization
        attr.deserialize_value(value)
    except Exception as e:
        print(f"Invalid data for {key}: {e}")
```

## Common Pitfalls & Best Practices

### ❌ DON'T: Query attribute_data with complex filters
```python
# Slow and unreliable
projects = Project.objects.filter(
    attribute_data__project_manager="john.doe"
)
```

### ✅ DO: Use dedicated fields or caching
```python
# Add frequently queried fields as model fields
# Or use cached properties for complex lookups
```

### ❌ DON'T: Modify attribute_data directly
```python
project.attribute_data["field"] = value  # Bypasses validation!
```

### ✅ DO: Use update_attribute_data
```python
project.update_attribute_data({"field": value})
```

### ❌ DON'T: Forget to save after update_attribute_data
```python
project.update_attribute_data(data)
# Missing: project.save()
```

### ✅ DO: Always save after updates
```python
project.update_attribute_data(data)
project.save()
```

### Performance Considerations

- **JSONField queries**: Use sparingly; prefer indexed model fields for filters
- **Prefetch related**: Always prefetch `value_choices` when loading attributes
- **Batch operations**: Use `bulk_create` and `bulk_update` for large datasets
- **Caching**: Use Redis cache for frequently accessed project schemas
- **Geometry queries**: Use spatial indexes for PostGIS operations

### Logging Conventions

```python
import logging
log = logging.getLogger(__name__)

# Use appropriate log levels
log.debug("Detailed debugging info")
log.info("General information")
log.warning("Warning: non-critical issue")
log.error("Error occurred", exc_info=True)
```

## Troubleshooting

### "Attribute not found" errors
Check that attribute exists and identifier matches exactly:
```python
python manage.py shell
>>> from projects.models import Attribute
>>> Attribute.objects.filter(identifier="your_field").exists()
```

### Serialization errors
Test attribute deserialization manually:
```python
attr = Attribute.objects.get(identifier="problem_field")
attr.deserialize_value(raw_value)  # Will raise if invalid
```

### Permission denied errors
Verify user privileges:
```python
user.has_privilege(project, "browse")  # Can view
user.has_privilege(project, "edit")    # Can modify
user.has_privilege(project, "create")  # Can create
user.has_privilege(project, "admin")   # Full access
```

### Django-Q tasks not running
```bash
# Check qcluster is running
docker-compose ps  # Should show qcluster container

# Monitor task queue
python manage.py qmonitor
```
