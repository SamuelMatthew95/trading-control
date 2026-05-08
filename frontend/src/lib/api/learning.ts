/**
 * Learning API endpoints — typed wrappers.
 */

import { API_ENDPOINTS, apiFetch } from '@/lib/apiClient'

export interface LearningProposalsResponse {
  proposals?: Array<Record<string, unknown>>
}

export async function getLearningProposals(): Promise<LearningProposalsResponse> {
  return apiFetch<LearningProposalsResponse>(API_ENDPOINTS.LEARNING_PROPOSALS)
}

export interface IcWeightsResponse {
  current_weights?: Record<string, number>
}

export async function getIcWeights(): Promise<IcWeightsResponse> {
  return apiFetch<IcWeightsResponse>(API_ENDPOINTS.LEARNING_IC_WEIGHTS)
}

export interface GradeRecord {
  grade: string
  score_pct: number
  timestamp: string
  metrics?: Record<string, number>
}

export interface LearningGradesResponse {
  grades?: GradeRecord[]
}

export async function getLearningGrades(): Promise<LearningGradesResponse> {
  return apiFetch<LearningGradesResponse>(API_ENDPOINTS.LEARNING_GRADES)
}

export interface ProposalUpdateResponse {
  ok?: boolean
}

export async function voteOnProposal(
  id: string,
  status: 'approved' | 'rejected',
): Promise<ProposalUpdateResponse> {
  return apiFetch<ProposalUpdateResponse>(
    `/dashboard/learning/proposals/${encodeURIComponent(id)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    },
  )
}
