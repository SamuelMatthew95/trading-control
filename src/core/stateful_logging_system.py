"""
Stateful Logging System with Database Persistence
Using enums for measurements and history tables for easy querying
"""

from __future__ import annotations
import asyncio
from typing import Dict, Any, List, Optional, TypedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import sqlite3
import json
import uuid
from contextlib import asynccontextmanager


class LogLevel(Enum):
    """Log levels for structured logging"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventType(Enum):
    """Event types for tracking"""
    AGENT_EXECUTION = "agent_execution"
    MISTAKE_ANALYSIS = "mistake_analysis"
    LEARNING_SESSION = "learning_session"
    TEAM_FORMATION = "team_formation"
    COLLABORATION = "collaboration"
    PERFORMANCE_EVALUATION = "performance_evaluation"
    SYSTEM_EVENT = "system_event"


class AgentStatus(Enum):
    """Agent status tracking"""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    LEARNING = "learning"
    COLLABORATING = "collaborating"
    ERROR = "error"
    RETIRED = "retired"


class PerformanceMetric(Enum):
    """Performance metrics that can be measured"""
    SUCCESS_RATE = "success_rate"
    EXECUTION_TIME = "execution_time"
    ERROR_RATE = "error_rate"
    COLLABORATION_SUCCESS = "collaboration_success"
    EXPERTISE_SCORE = "expertise_score"
    LEARNING_RATE = "learning_rate"
    TEAM_EFFECTIVENESS = "team_effectiveness"


class DatabaseManager:
    """Manages SQLite database for stateful logging"""
    
    def __init__(self, db_path: str = "trading_system.db"):
        self.db_path = db_path
        self._initialize_database()
    
    def _initialize_database(self):
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    event_type TEXT NOT NULL,
                    log_level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    metadata TEXT,
                    execution_id TEXT,
                    FOREIGN KEY (execution_id) REFERENCES execution_history(execution_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_history (
                    execution_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    input_data TEXT,
                    output_data TEXT,
                    success BOOLEAN NOT NULL,
                    error_message TEXT,
                    execution_time_ms INTEGER,
                    timestamp DATETIME NOT NULL,
                    performance_metrics TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    metric_type TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    timestamp DATETIME NOT NULL,
                    context TEXT,
                    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    expertise_areas TEXT,
                    total_executions INTEGER DEFAULT 0,
                    successful_executions INTEGER DEFAULT 0,
                    failed_executions INTEGER DEFAULT 0
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learning_sessions (
                    session_id TEXT PRIMARY KEY,
                    session_type TEXT NOT NULL,
                    participants TEXT NOT NULL,
                    start_time DATETIME NOT NULL,
                    end_time DATETIME,
                    status TEXT NOT NULL,
                    outcomes TEXT,
                    performance_metrics TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS team_formations (
                    team_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    members TEXT NOT NULL,
                    formation_time DATETIME NOT NULL,
                    dissolution_time DATETIME,
                    status TEXT NOT NULL,
                    performance_score REAL
                )
            """)
            
            # Create indexes for efficient querying
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_logs_timestamp ON agent_logs(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_logs_agent_id ON agent_logs(agent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_history_timestamp ON execution_history(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_performance_timestamp ON agent_performance(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_performance_agent_id ON agent_performance(agent_id)")
            
            conn.commit()
    
    @asynccontextmanager
    async def get_connection(self):
        """Get database connection with proper cleanup"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    async def log_agent_event(self, agent_id: str, event_type: EventType, 
                            log_level: LogLevel, status: AgentStatus, 
                            message: str = None, metadata: Dict[str, Any] = None,
                            execution_id: str = None):
        """Log agent event to database"""
        async with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO agent_logs 
                (agent_id, timestamp, event_type, log_level, status, message, metadata, execution_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                agent_id,
                datetime.now().isoformat(),
                event_type.value,
                log_level.value,
                status.value,
                message,
                json.dumps(metadata) if metadata else None,
                execution_id
            ))
            conn.commit()
    
    async def record_execution(self, execution_id: str, agent_id: str, action: str,
                             input_data: Dict[str, Any], output_data: Dict[str, Any] = None,
                             success: bool = True, error_message: str = None,
                             execution_time_ms: int = 0, performance_metrics: Dict[str, float] = None):
        """Record execution to database"""
        async with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO execution_history 
                (execution_id, agent_id, action, input_data, output_data, success, 
                 error_message, execution_time_ms, timestamp, performance_metrics)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                execution_id,
                agent_id,
                action,
                json.dumps(input_data),
                json.dumps(output_data) if output_data else None,
                success,
                error_message,
                execution_time_ms,
                datetime.now().isoformat(),
                json.dumps(performance_metrics) if performance_metrics else None
            ))
            conn.commit()
    
    async def record_performance_metric(self, agent_id: str, metric_type: PerformanceMetric,
                                      metric_value: float, context: Dict[str, Any] = None):
        """Record performance metric to database"""
        async with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO agent_performance 
                (agent_id, metric_type, metric_value, timestamp, context)
                VALUES (?, ?, ?, ?, ?)
            """, (
                agent_id,
                metric_type.value,
                metric_value,
                datetime.now().isoformat(),
                json.dumps(context) if context else None
            ))
            conn.commit()
    
    async def update_agent_status(self, agent_id: str, status: AgentStatus):
        """Update agent status in database"""
        async with self.get_connection() as conn:
            # Check if agent exists
            cursor = conn.execute("SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,))
            if not cursor.fetchone():
                # Create new agent record
                conn.execute("""
                    INSERT INTO agents 
                    (agent_id, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    agent_id,
                    status.value,
                    datetime.now().isoformat(),
                    datetime.now().isoformat()
                ))
            else:
                # Update existing agent
                conn.execute("""
                    UPDATE agents 
                    SET status = ?, updated_at = ?
                    WHERE agent_id = ?
                """, (
                    status.value,
                    datetime.now().isoformat(),
                    agent_id
                ))
            conn.commit()
    
    async def get_agent_history(self, agent_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get agent history from database"""
        async with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM agent_logs 
                WHERE agent_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (agent_id, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    async def get_performance_metrics(self, agent_id: str, metric_type: PerformanceMetric = None,
                                     hours: int = 24) -> List[Dict[str, Any]]:
        """Get performance metrics from database"""
        async with self.get_connection() as conn:
            query = """
                SELECT * FROM agent_performance 
                WHERE agent_id = ? AND timestamp >= datetime('now', '-{} hours')
            """.format(hours)
            
            params = [agent_id]
            if metric_type:
                query += " AND metric_type = ?"
                params.append(metric_type.value)
            
            query += " ORDER BY timestamp DESC"
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    async def get_execution_history(self, agent_id: str = None, success: bool = None,
                                  hours: int = 24) -> List[Dict[str, Any]]:
        """Get execution history from database"""
        async with self.get_connection() as conn:
            query = """
                SELECT * FROM execution_history 
                WHERE timestamp >= datetime('now', '-{} hours')
            """.format(hours)
            
            params = []
            if agent_id:
                query += " AND agent_id = ?"
                params.append(agent_id)
            
            if success is not None:
                query += " AND success = ?"
                params.append(success)
            
            query += " ORDER BY timestamp DESC"
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    async def get_system_summary(self) -> Dict[str, Any]:
        """Get system summary from database"""
        async with self.get_connection() as conn:
            # Agent counts by status
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count 
                FROM agents 
                GROUP BY status
            """)
            agent_status_counts = {row['status']: row['count'] for row in cursor.fetchall()}
            
            # Recent execution stats
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_executions,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_executions,
                    AVG(execution_time_ms) as avg_execution_time
                FROM execution_history 
                WHERE timestamp >= datetime('now', '-24 hours')
            """)
            exec_stats = cursor.fetchone()
            
            # Performance metric averages
            cursor = conn.execute("""
                SELECT metric_type, AVG(metric_value) as avg_value
                FROM agent_performance 
                WHERE timestamp >= datetime('now', '-24 hours')
                GROUP BY metric_type
            """)
            performance_averages = {row['metric_type']: row['avg_value'] for row in cursor.fetchall()}
            
            return {
                "agent_status_counts": agent_status_counts,
                "execution_stats_24h": {
                    "total_executions": exec_stats['total_executions'] or 0,
                    "successful_executions": exec_stats['successful_executions'] or 0,
                    "avg_execution_time_ms": exec_stats['avg_execution_time'] or 0
                },
                "performance_averages_24h": performance_averages,
                "timestamp": datetime.now().isoformat()
            }


class StatefulLogger:
    """Stateful logger using database persistence"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    async def log_agent_execution(self, agent_id: str, execution_id: str, action: str,
                                 input_data: Dict[str, Any], output_data: Dict[str, Any] = None,
                                 success: bool = True, error_message: str = None,
                                 execution_time_ms: int = 0):
        """Log agent execution with full context"""
        # Record execution
        await self.db.record_execution(
            execution_id, agent_id, action, input_data, output_data,
            success, error_message, execution_time_ms
        )
        
        # Log event
        status = AgentStatus.ERROR if not success else AgentStatus.ACTIVE
        log_level = LogLevel.ERROR if not success else LogLevel.INFO
        
        await self.db.log_agent_event(
            agent_id, EventType.AGENT_EXECUTION, log_level, status,
            f"Agent {agent_id} {action} {'succeeded' if success else 'failed'}",
            {"execution_time_ms": execution_time_ms, "action": action},
            execution_id
        )
        
        # Update agent status
        await self.db.update_agent_status(agent_id, status)
        
        # Record performance metrics
        if success:
            await self.db.record_performance_metric(
                agent_id, PerformanceMetric.EXECUTION_TIME, execution_time_ms,
                {"action": action}
            )
    
    async def log_mistake_analysis(self, agent_id: str, execution_id: str, 
                                 mistake_pattern: str, analysis: Dict[str, Any]):
        """Log mistake analysis"""
        await self.db.log_agent_event(
            agent_id, EventType.MISTAKE_ANALYSIS, LogLevel.INFO, AgentStatus.LEARNING,
            f"Mistake analysis completed: {mistake_pattern}",
            {"pattern": mistake_pattern, "analysis": analysis},
            execution_id
        )
        
        await self.db.update_agent_status(agent_id, AgentStatus.LEARNING)
    
    async def log_learning_session(self, session_id: str, participants: List[str],
                                session_type: str, outcomes: Dict[str, Any]):
        """Log learning session"""
        # Record session in database
        async with self.db.get_connection() as conn:
            conn.execute("""
                INSERT INTO learning_sessions 
                (session_id, session_type, participants, start_time, status, outcomes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                session_type,
                json.dumps(participants),
                datetime.now().isoformat(),
                "completed",
                json.dumps(outcomes)
            ))
            conn.commit()
        
        # Log events for each participant
        for participant_id in participants:
            await self.db.log_agent_event(
                participant_id, EventType.LEARNING_SESSION, LogLevel.INFO, AgentStatus.LEARNING,
                f"Participated in learning session: {session_type}",
                {"session_id": session_id, "participants": participants}
            )
    
    async def log_team_formation(self, team_id: str, members: List[str], task_type: str):
        """Log team formation"""
        # Record team in database
        async with self.db.get_connection() as conn:
            conn.execute("""
                INSERT INTO team_formations 
                (team_id, task_type, members, formation_time, status)
                VALUES (?, ?, ?, ?, ?)
            """, (
                team_id,
                task_type,
                json.dumps(members),
                datetime.now().isoformat(),
                "active"
            ))
            conn.commit()
        
        # Log events for each member
        for member_id in members:
            await self.db.log_agent_event(
                member_id, EventType.TEAM_FORMATION, LogLevel.INFO, AgentStatus.COLLABORATING,
                f"Joined team for {task_type}",
                {"team_id": team_id, "members": members}
            )
            
            await self.db.update_agent_status(member_id, AgentStatus.COLLABORATING)
    
    async def log_performance_evaluation(self, agent_id: str, metrics: Dict[str, float]):
        """Log performance evaluation"""
        for metric_name, metric_value in metrics.items():
            try:
                metric_type = PerformanceMetric(metric_name)
                await self.db.record_performance_metric(agent_id, metric_type, metric_value)
            except ValueError:
                # Skip unknown metric types
                continue
        
        await self.db.log_agent_event(
            agent_id, EventType.PERFORMANCE_EVALUATION, LogLevel.INFO, AgentStatus.ACTIVE,
            "Performance evaluation completed",
            {"metrics": metrics}
        )
    
    async def log_system_event(self, event_type: EventType, message: str, 
                             metadata: Dict[str, Any] = None, log_level: LogLevel = LogLevel.INFO):
        """Log system-wide event"""
        await self.db.log_agent_event(
            "system", event_type, log_level, AgentStatus.ACTIVE,
            message, metadata
        )


class TestDatabaseManager:
    """Test utilities for database operations"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    async def setup_test_data(self):
        """Set up test data for testing"""
        # Create test agents
        test_agents = [
            ("agent_001", AgentStatus.ACTIVE),
            ("agent_002", AgentStatus.LEARNING),
            ("agent_003", AgentStatus.COLLABORATING),
            ("agent_004", AgentStatus.ERROR),
            ("agent_005", AgentStatus.RETIRED)
        ]
        
        for agent_id, status in test_agents:
            await self.db.update_agent_status(agent_id, status)
        
        # Create test executions
        test_executions = [
            ("exec_001", "agent_001", "analyze_market", True, 150),
            ("exec_002", "agent_001", "analyze_market", True, 120),
            ("exec_003", "agent_002", "assess_risk", False, 200),
            ("exec_004", "agent_003", "execute_trade", True, 80),
            ("exec_005", "agent_004", "validate_data", False, 300)
        ]
        
        for exec_id, agent_id, action, success, exec_time in test_executions:
            await self.db.record_execution(
                exec_id, agent_id, action,
                {"test": "data"}, {"result": "success"} if success else None,
                success, None if success else "Test error", exec_time
            )
        
        # Create test performance metrics
        test_metrics = [
            ("agent_001", PerformanceMetric.SUCCESS_RATE, 0.85),
            ("agent_001", PerformanceMetric.EXECUTION_TIME, 135.0),
            ("agent_002", PerformanceMetric.SUCCESS_RATE, 0.65),
            ("agent_003", PerformanceMetric.COLLABORATION_SUCCESS, 0.92),
            ("agent_004", PerformanceMetric.ERROR_RATE, 0.45)
        ]
        
        for agent_id, metric_type, value in test_metrics:
            await self.db.record_performance_metric(agent_id, metric_type, value)
    
    async def cleanup_test_data(self):
        """Clean up test data"""
        async with self.db.get_connection() as conn:
            conn.execute("DELETE FROM agent_logs WHERE agent_id LIKE 'agent_%'")
            conn.execute("DELETE FROM execution_history WHERE agent_id LIKE 'agent_%'")
            conn.execute("DELETE FROM agent_performance WHERE agent_id LIKE 'agent_%'")
            conn.execute("DELETE FROM agents WHERE agent_id LIKE 'agent_%'")
            conn.execute("DELETE FROM learning_sessions WHERE session_id LIKE 'test_%'")
            conn.execute("DELETE FROM team_formations WHERE team_id LIKE 'test_%'")
            conn.commit()
    
    async def verify_data_integrity(self) -> Dict[str, Any]:
        """Verify data integrity after tests"""
        async with self.db.get_connection() as conn:
            # Count records
            agent_count = conn.execute("SELECT COUNT(*) FROM agents WHERE agent_id LIKE 'agent_%'").fetchone()[0]
            execution_count = conn.execute("SELECT COUNT(*) FROM execution_history WHERE agent_id LIKE 'agent_%'").fetchone()[0]
            metric_count = conn.execute("SELECT COUNT(*) FROM agent_performance WHERE agent_id LIKE 'agent_%'").fetchone()[0]
            
            return {
                "agents": agent_count,
                "executions": execution_count,
                "metrics": metric_count,
                "integrity_check": "passed" if agent_count > 0 and execution_count > 0 else "failed"
            }


# Factory function
def create_stateful_logging_system(db_path: str = "trading_system.db") -> Tuple[DatabaseManager, StatefulLogger, TestDatabaseManager]:
    """Create stateful logging system with database persistence"""
    db_manager = DatabaseManager(db_path)
    logger = StatefulLogger(db_manager)
    test_manager = TestDatabaseManager(db_manager)
    
    return db_manager, logger, test_manager
