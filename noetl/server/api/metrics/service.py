"""
NoETL Metrics API Service - Business logic for metrics operations.

Handles:
- Metric collection and storage
- System metrics gathering
- Prometheus format export
- Partition management
- TTL management
"""

import time
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

import psutil
from psycopg.rows import dict_row

from noetl.core.common import get_async_db_connection, get_snowflake_id
from noetl.core.logger import setup_logger
from noetl.core.config import get_settings, get_worker_settings
from .schema import (
    MetricData,
    MetricsPayload,
    MetricReportResponse,
    ComponentInfo,
    ComponentListResponse,
    MetricQueryResponse,
    SelfReportResponse,
    CleanupResponse,
    PartitionCreateResponse,
    TTLUpdateResponse
)

logger = setup_logger(__name__, include_location=True)


class MetricsService:
    """Service for metrics collection, storage, and management."""
    
    @staticmethod
    async def report_metrics(payload: MetricsPayload) -> MetricReportResponse:
        """
        Report metrics from workers or servers.
        
        Args:
            payload: Metrics payload with runtime_id or component_name
            
        Returns:
            MetricReportResponse with insertion status
        """
        runtime_id = payload.runtime_id
        
        # Resolve runtime_id from component_name if not provided
        if not runtime_id and payload.component_name:
            runtime_id = await MetricsService._resolve_runtime_id(payload.component_name)
        
        if not runtime_id:
            raise ValueError("Either runtime_id or component_name must be provided")
        
        # Insert metrics
        inserted_count = await MetricsService._insert_metrics(runtime_id, payload.metrics)
        
        return MetricReportResponse(
            status="ok",
            runtime_id=runtime_id,
            metrics_inserted=inserted_count
        )
    
    @staticmethod
    async def query_metrics(
        runtime_id: Optional[int] = None,
        component_name: Optional[str] = None,
        metric_name: Optional[str] = None,
        metric_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 1000
    ) -> MetricQueryResponse:
        """
        Query metrics with optional filtering.
        
        Args:
            runtime_id: Filter by runtime ID
            component_name: Filter by component name
            metric_name: Filter by metric name
            metric_type: Filter by metric type
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            limit: Maximum results
            
        Returns:
            MetricQueryResponse with matching metrics
        """
        # Build dynamic query
        where_clauses = []
        params = []
        
        if runtime_id:
            where_clauses.append("m.runtime_id = %s")
            params.append(runtime_id)
        elif component_name:
            where_clauses.append("r.name = %s")
            params.append(component_name)
        
        if metric_name:
            where_clauses.append("m.metric_name = %s")
            params.append(metric_name)
        
        if metric_type:
            where_clauses.append("m.metric_type = %s")
            params.append(metric_type)
        
        if start_time:
            where_clauses.append("m.created_at >= %s")
            params.append(start_time)
        
        if end_time:
            where_clauses.append("m.created_at <= %s")
            params.append(end_time)
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        query = f"""
            SELECT 
                m.metric_id, m.runtime_id, r.name as component_name, r.component_type,
                m.metric_name, m.metric_type, m.metric_value, m.labels, 
                m.help_text, m.unit, m.timestamp, m.created_at
            FROM noetl.metric m
            JOIN noetl.runtime r ON m.runtime_id = r.runtime_id
            WHERE {where_sql}
            ORDER BY m.created_at DESC
            LIMIT %s
        """
        params.append(limit)
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
                
                metrics = []
                for row in rows:
                    labels_data = json.loads(row[7]) if row[7] else None
                    metrics.append({
                        "metric_id": row[0],
                        "runtime_id": row[1],
                        "component_name": row[2],
                        "component_type": row[3],
                        "metric_name": row[4],
                        "metric_type": row[5],
                        "metric_value": row[6],
                        "labels": labels_data,
                        "help_text": row[8],
                        "unit": row[9],
                        "timestamp": row[10].isoformat() if row[10] else None,
                        "created_at": row[11].isoformat() if row[11] else None
                    })
        
        return MetricQueryResponse(
            metrics=metrics,
            count=len(metrics),
            limit=limit
        )
    
    @staticmethod
    async def generate_prometheus_format(
        runtime_id: Optional[int] = None,
        component_name: Optional[str] = None
    ) -> str:
        """
        Generate metrics in Prometheus format for scraping.
        
        Args:
            runtime_id: Filter by runtime ID
            component_name: Filter by component name
            
        Returns:
            String in Prometheus text format
        """
        # Build query with optional filtering
        where_clauses = ["1=1"]
        params = []
        
        if runtime_id:
            where_clauses.append("m.runtime_id = %s")
            params.append(runtime_id)
        elif component_name:
            where_clauses.append("r.name = %s")
            params.append(component_name)
        
        where_sql = " AND ".join(where_clauses)
        
        # Get recent metrics (last 5 minutes)
        query = f"""
            WITH recent_metrics AS (
                SELECT DISTINCT ON (m.runtime_id, m.metric_name, m.labels)
                    m.metric_name, m.metric_type, m.metric_value, m.labels,
                    m.help_text, r.name as component_name, r.component_type
                FROM noetl.metric m
                JOIN noetl.runtime r ON m.runtime_id = r.runtime_id
                WHERE {where_sql}
                  AND m.created_at >= now() - interval '5 minutes'
                ORDER BY m.runtime_id, m.metric_name, m.labels, m.created_at DESC
            )
            SELECT * FROM recent_metrics
            ORDER BY metric_name, component_name
        """
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
        
        # Group metrics by name for Prometheus format
        metrics_by_name = {}
        for row in rows:
            metric_name, metric_type, metric_value, labels_json, help_text, component_name, component_type = row
            
            if metric_name not in metrics_by_name:
                metrics_by_name[metric_name] = {
                    "type": metric_type,
                    "help": help_text or f"NoETL metric: {metric_name}",
                    "values": []
                }
            
            # Parse labels and add component info
            labels = json.loads(labels_json) if labels_json else {}
            labels["component"] = component_name
            labels["component_type"] = component_type
            
            # Format labels for Prometheus
            label_str = ""
            if labels:
                label_pairs = [f'{k}="{v}"' for k, v in labels.items()]
                label_str = "{" + ",".join(label_pairs) + "}"
            
            metrics_by_name[metric_name]["values"].append({
                "labels": label_str,
                "value": metric_value
            })
        
        # Generate Prometheus format
        lines = []
        for metric_name, metric_data in metrics_by_name.items():
            # Add HELP and TYPE lines
            lines.append(f"# HELP {metric_name} {metric_data['help']}")
            lines.append(f"# TYPE {metric_name} {metric_data['type']}")
            
            # Add metric values
            for value_data in metric_data["values"]:
                lines.append(f"{metric_name}{value_data['labels']} {value_data['value']}")
        
        return "\n".join(lines) + "\n"
    
    @staticmethod
    async def list_components() -> ComponentListResponse:
        """
        List all components registered in runtime table.
        
        Returns:
            ComponentListResponse with all components
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT runtime_id, name, component_type, status, last_heartbeat
                    FROM noetl.runtime
                    ORDER BY component_type, name
                    """
                )
                rows = await cur.fetchall()
                
                components = []
                for row in rows:
                    components.append(ComponentInfo(
                        runtime_id=row[0],
                        name=row[1],
                        component_type=row[2],
                        status=row[3],
                        last_heartbeat=row[4].isoformat() if row[4] else None
                    ))
        
        return ComponentListResponse(components=components)
    
    @staticmethod
    def collect_system_metrics() -> List[MetricData]:
        """
        Collect basic system metrics for the current process.
        
        Returns:
            List of MetricData with system metrics
        """
        metrics = []
        
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=0.1)
            metrics.append(MetricData(
                metric_name="noetl_system_cpu_usage_percent",
                metric_type="gauge",
                metric_value=cpu_percent,
                help_text="CPU usage percentage",
                unit="percent"
            ))
            
            # Memory usage
            memory = psutil.virtual_memory()
            metrics.append(MetricData(
                metric_name="noetl_system_memory_usage_bytes",
                metric_type="gauge",
                metric_value=memory.used,
                help_text="Memory usage in bytes",
                unit="bytes"
            ))
            
            metrics.append(MetricData(
                metric_name="noetl_system_memory_usage_percent",
                metric_type="gauge",
                metric_value=memory.percent,
                help_text="Memory usage percentage",
                unit="percent"
            ))
            
            # Process info
            process = psutil.Process()
            metrics.append(MetricData(
                metric_name="noetl_process_cpu_percent",
                metric_type="gauge",
                metric_value=process.cpu_percent(),
                help_text="Process CPU usage percentage",
                unit="percent"
            ))
            
            memory_info = process.memory_info()
            metrics.append(MetricData(
                metric_name="noetl_process_memory_rss_bytes",
                metric_type="gauge",
                metric_value=memory_info.rss,
                help_text="Process RSS memory in bytes",
                unit="bytes"
            ))
            
            # Process start time
            start_time = process.create_time()
            metrics.append(MetricData(
                metric_name="noetl_process_start_time_seconds",
                metric_type="gauge",
                metric_value=start_time,
                help_text="Process start time since unix epoch",
                unit="seconds"
            ))
            
        except Exception as e:
            logger.debug(f"Error collecting system metrics: {e}")
        
        return metrics
    
    @staticmethod
    async def self_report_metrics(component_name: Optional[str] = None) -> SelfReportResponse:
        """
        Allow server or worker to report its own system metrics.
        
        Args:
            component_name: Component name (auto-detected if not provided)
            
        Returns:
            SelfReportResponse with report status
        """
        # Determine component name
        if not component_name:
            worker_settings = get_worker_settings()
            pool_name = (worker_settings.pool_name or "").strip()
            if pool_name:
                component_name = pool_name
            else:
                component_name = get_settings().server_name

        # Collect system metrics
        system_metrics = MetricsService.collect_system_metrics()
        
        # Add uptime metric
        try:
            process = psutil.Process()
            uptime = time.time() - process.create_time()
            system_metrics.append(MetricData(
                metric_name="noetl_uptime_seconds",
                metric_type="gauge",
                metric_value=uptime,
                help_text="Component uptime in seconds",
                unit="seconds"
            ))
        except Exception:
            pass
        
        # Resolve runtime ID
        runtime_id = await MetricsService._resolve_runtime_id(component_name)
        
        # Insert metrics
        inserted_count = await MetricsService._insert_metrics(runtime_id, system_metrics)
        
        return SelfReportResponse(
            status="ok",
            component_name=component_name,
            runtime_id=runtime_id,
            metrics_reported=inserted_count
        )
    
    @staticmethod
    async def cleanup_expired_metrics() -> CleanupResponse:
        """
        Clean up expired metrics by dropping old partitions.
        
        Returns:
            CleanupResponse with dropped partitions
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT noetl.cleanup_expired_metrics()")
                result = await cur.fetchone()
                dropped_partitions = result[0] if result else []
                
            await conn.commit()
        
        return CleanupResponse(
            status="ok",
            dropped_partitions=dropped_partitions,
            dropped_count=len(dropped_partitions),
            message=f"Dropped {len(dropped_partitions)} expired metric partitions"
        )
    
    @staticmethod
    async def create_metric_partitions(days_ahead: int = 7) -> PartitionCreateResponse:
        """
        Create metric partitions for upcoming days.
        
        Args:
            days_ahead: Number of days ahead to create partitions for
            
        Returns:
            PartitionCreateResponse with created partitions
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT noetl.create_metric_partitions_ahead(%s)",
                    (days_ahead,)
                )
                result = await cur.fetchone()
                partition_names = result[0] if result else []
                
            await conn.commit()
        
        return PartitionCreateResponse(
            status="ok",
            created_partitions=partition_names,
            created_count=len(partition_names),
            days_ahead=days_ahead,
            message=f"Created {len(partition_names)} metric partitions"
        )
    
    @staticmethod
    async def set_metric_ttl(metric_name: str, ttl_days: int = 1) -> TTLUpdateResponse:
        """
        Set custom TTL for specific metrics.
        
        Args:
            metric_name: Name of the metric to update
            ttl_days: Number of days from now until expiration
            
        Returns:
            TTLUpdateResponse with update status
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT noetl.set_metric_ttl(%s, %s::interval)",
                    (metric_name, f"{ttl_days} days")
                )
                result = await cur.fetchone()
                updated_count = result[0] if result else 0
                
            await conn.commit()
        
        return TTLUpdateResponse(
            status="ok",
            metric_name=metric_name,
            updated_metrics=updated_count,
            new_ttl_days=ttl_days,
            message=f"Updated TTL for {updated_count} metrics named '{metric_name}'"
        )
    
    @staticmethod
    async def extend_component_metrics_ttl(
        component_name: str,
        ttl_days: int = 1
    ) -> TTLUpdateResponse:
        """
        Extend TTL for all metrics of a component.
        
        Args:
            component_name: Name of the component (runtime name)
            ttl_days: Number of days from now until expiration
            
        Returns:
            TTLUpdateResponse with update status
        """
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT noetl.extend_component_metrics_ttl(%s, %s::interval)",
                    (component_name, f"{ttl_days} days")
                )
                result = await cur.fetchone()
                updated_count = result[0] if result else 0
                
            await conn.commit()
        
        return TTLUpdateResponse(
            status="ok",
            component_name=component_name,
            updated_metrics=updated_count,
            new_ttl_days=ttl_days,
            message=f"Extended TTL for {updated_count} metrics from component '{component_name}'"
        )
    
    @staticmethod
    async def auto_cleanup_expired_metrics() -> int:
        """
        Background function to automatically clean up expired metrics.
        
        Returns:
            Number of partitions dropped
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT noetl.cleanup_expired_metrics()")
                    result = await cur.fetchone()
                    dropped_partitions = result[0] if result else []
                    
                await conn.commit()
                
            if dropped_partitions:
                logger.info(
                    f"Auto-cleanup: dropped {len(dropped_partitions)} expired metric partitions: "
                    f"{dropped_partitions}"
                )
            
            return len(dropped_partitions)
            
        except Exception as e:
            logger.exception(f"Error in auto-cleanup of expired metrics: {e}")
            return 0
    
    @staticmethod
    async def auto_create_metric_partitions() -> int:
        """
        Background function to automatically create metric partitions for upcoming days.
        
        Returns:
            Number of partitions created
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cur:
                    # Create partitions for the next 7 days
                    await cur.execute("SELECT noetl.create_metric_partitions_ahead(7)")
                    result = await cur.fetchone()
                    partition_names = result[0] if result else []
                    
                await conn.commit()
                
            if partition_names:
                logger.info(
                    f"Auto-partition creation: created {len(partition_names)} metric partitions"
                )
            
            return len(partition_names)
            
        except Exception as e:
            logger.exception(f"Error in auto-creation of metric partitions: {e}")
            return 0
    
    # Helper methods
    
    @staticmethod
    async def _resolve_runtime_id(component_name: str) -> int:
        """Resolve runtime ID from component name."""
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT runtime_id FROM noetl.runtime WHERE name = %s",
                    (component_name,)
                )
                row = await cur.fetchone()
                if not row:
                    raise ValueError(
                        f"Component '{component_name}' not found in runtime registry"
                    )
                return row[0]
    
    @staticmethod
    async def _insert_metrics(runtime_id: int, metrics: List[MetricData]) -> int:
        """Insert metrics into database."""
        inserted_count = 0
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                for metric in metrics:
                    try:
                        metric_id = get_snowflake_id()
                    except Exception:
                        metric_id = int(time.time() * 1000000)  # Fallback
                    
                    timestamp = metric.timestamp or datetime.now(timezone.utc)
                    labels_json = json.dumps(metric.labels) if metric.labels else None
                    
                    await cur.execute(
                        """
                        INSERT INTO noetl.metric 
                        (metric_id, runtime_id, metric_name, metric_type, metric_value, 
                         labels, help_text, unit, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            metric_id, runtime_id, metric.metric_name, 
                            metric.metric_type, metric.metric_value,
                            labels_json, metric.help_text, metric.unit, timestamp
                        )
                    )
                    inserted_count += 1
            
            await conn.commit()
        
        return inserted_count
