"""
Agents package for trading system
"""

from .deterministic_trading_system import (
    DeterministicTradingSystem, SelfImprovingAgent,
    AgentMetrics, LearningSignal, AgentCommunicationProtocol,
    create_deterministic_trading_system
)

from .intelligent_learning_system import (
    CollaborativeLearningDatabase, IntelligentLearningManager,
    DynamicTeamManager, MistakePattern, ExpertiseArea,
    MistakeAnalysis, SuccessPattern, AgentExpertise, TeamFormation,
    create_intelligent_learning_system
)

__all__ = [
    # Deterministic trading
    'DeterministicTradingSystem', 'SelfImprovingAgent',
    'AgentMetrics', 'LearningSignal', 'AgentCommunicationProtocol',
    'create_deterministic_trading_system',
    
    # Intelligent learning
    'CollaborativeLearningDatabase', 'IntelligentLearningManager',
    'DynamicTeamManager', 'MistakePattern', 'ExpertiseArea',
    'MistakeAnalysis', 'SuccessPattern', 'AgentExpertise', 'TeamFormation',
    'create_intelligent_learning_system'
]
