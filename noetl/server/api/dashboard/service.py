"""
NoETL Dashboard API Service - Business logic for dashboard operations.

Handles:
- Dashboard statistics computation
- Widget data retrieval
- Execution summaries
- Health checks
"""

from typing import List
from noetl.core.logger import setup_logger
from .schema import (
    DashboardStatsResponse,
    DashboardWidget,
    DashboardWidgetsResponse,
    HealthCheckResponse
)

logger = setup_logger(__name__, include_location=True)


class DashboardService:
    """Service class for dashboard operations."""
    
    @staticmethod
    async def get_dashboard_stats() -> DashboardStatsResponse:
        """
        Get dashboard statistics.
        
        Queries the database for real-time execution and playbook statistics.
        
        Returns:
            DashboardStatsResponse with statistics
        """
        try:
            from noetl.core.db.pool import get_pool_connection
            
            async with get_pool_connection() as conn:
                async with conn.cursor() as cur:
                    # Count total unique executions
                    await cur.execute("""
                        SELECT COUNT(DISTINCT execution_id) as total
                        FROM noetl.event
                    """)
                    row = await cur.fetchone()
                    total_executions = row["total"] if row else 0
                    
                    # Count successful executions (have workflow_completed event)
                    await cur.execute("""
                        SELECT COUNT(DISTINCT execution_id) as total
                        FROM noetl.event
                        WHERE event_type = 'workflow_completed'
                        AND status = 'COMPLETED'
                    """)
                    row = await cur.fetchone()
                    successful_executions = row["total"] if row else 0
                    
                    # Count failed executions (have step_failed or error status)
                    await cur.execute("""
                        SELECT COUNT(DISTINCT execution_id) as total
                        FROM noetl.event
                        WHERE event_type IN ('step.exit', 'workflow_completed')
                        AND status IN ('FAILED', 'ERROR')
                    """)
                    row = await cur.fetchone()
                    failed_executions = row["total"] if row else 0
                    
                    # Count total playbooks in catalog
                    await cur.execute("""
                        SELECT COUNT(*) as total
                        FROM noetl.catalog
                        WHERE kind = 'Playbook'
                    """)
                    row = await cur.fetchone()
                    total_playbooks = row["total"] if row else 0
                    
                    # Count active workflows (executions with RUNNING status in last hour)
                    await cur.execute("""
                        SELECT COUNT(DISTINCT execution_id) as total
                        FROM noetl.event
                        WHERE status = 'RUNNING'
                        AND created_at > NOW() - INTERVAL '1 hour'
                    """)
                    row = await cur.fetchone()
                    active_workflows = row["total"] if row else 0
            
            return DashboardStatsResponse(
                status="ok",
                stats={
                    "total_executions": total_executions,
                    "successful_executions": successful_executions,
                    "failed_executions": failed_executions,
                    "total_playbooks": total_playbooks,
                    "active_workflows": active_workflows
                },
                total_executions=total_executions,
                successful_executions=successful_executions,
                failed_executions=failed_executions,
                total_playbooks=total_playbooks,
                active_workflows=active_workflows
            )
        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}")
            # Return empty stats on error
            return DashboardStatsResponse(
                status="error",
                stats={},
                total_executions=0,
                successful_executions=0,
                failed_executions=0,
                total_playbooks=0,
                active_workflows=0
            )
    
    @staticmethod
    async def get_dashboard_widgets() -> DashboardWidgetsResponse:
        """
        Get dashboard widgets configuration.
        
        Returns widget configurations for the dashboard UI.
        Widgets are statically defined based on common monitoring needs.
        
        Returns:
            DashboardWidgetsResponse with widgets
        """
        try:
            # Define standard dashboard widgets
            widgets = [
                {
                    "id": "execution_stats",
                    "type": "metric",
                    "title": "Execution Statistics",
                    "description": "Overview of execution counts and success rates"
                },
                {
                    "id": "recent_executions",
                    "type": "table",
                    "title": "Recent Executions",
                    "description": "List of most recent playbook executions",
                    "config": {"limit": 10}
                },
                {
                    "id": "execution_trend",
                    "type": "chart",
                    "title": "Execution Trend",
                    "description": "Execution volume over time",
                    "config": {"timeRange": "24h", "chartType": "line"}
                },
                {
                    "id": "success_rate",
                    "type": "metric",
                    "title": "Success Rate",
                    "description": "Percentage of successful executions"
                },
                {
                    "id": "active_playbooks",
                    "type": "list",
                    "title": "Active Playbooks",
                    "description": "Playbooks with recent execution activity",
                    "config": {"limit": 5}
                }
            ]
            
            return DashboardWidgetsResponse(
                widgets=widgets
            )
        except Exception as e:
            logger.error(f"Error getting dashboard widgets: {e}")
            return DashboardWidgetsResponse(
                widgets=[]
            )
    
    @staticmethod
    async def health_check() -> HealthCheckResponse:
        """
        Perform health check.
        
        Returns:
            HealthCheckResponse with status
        """
        return HealthCheckResponse(
            status="ok"
        )
