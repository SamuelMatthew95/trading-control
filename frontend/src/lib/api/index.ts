export {
  getDashboardState,
  getKillSwitch,
  setKillSwitch,
  getTradeFeed,
  getPerformanceTrends,
  getAgentInstances,
  getEventsHistory,
  getTrace,
  getDashboardStateUrl,
  type TradeFeedResponse,
  type PerformanceTrendsResponse,
  type AgentInstancesResponse,
} from './dashboard'

export {
  getLearningProposals,
  getIcWeights,
  getLearningGrades,
  voteOnProposal,
  type LearningProposalsResponse,
  type IcWeightsResponse,
  type LearningGradesResponse,
  type GradeRecord,
  type ProposalUpdateResponse,
} from './learning'
