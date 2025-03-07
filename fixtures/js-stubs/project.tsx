import type {Project as TProject} from 'sentry/types';

import {Organization} from './organization';
import {Team} from './team';

export function Project(params: Partial<TProject> = {}): TProject {
  const team = Team();
  return {
    id: '2',
    slug: 'project-slug',
    name: 'Project Name',
    access: ['project:read'],
    hasAccess: true,
    isMember: true,
    isBookmarked: false,
    team,
    teams: [],
    environments: [],
    features: [],
    eventProcessing: {
      symbolicationDegraded: false,
    },
    dateCreated: new Date().toISOString(),
    digestsMaxDelay: 0,
    digestsMinDelay: 0,
    dynamicSamplingBiases: null,
    firstEvent: null,
    firstTransactionEvent: false,
    groupingAutoUpdate: false,
    groupingConfig: '',
    hasMinifiedStackTrace: false,
    hasProfiles: false,
    hasReplays: false,
    hasSessions: false,
    isInternal: false,
    organization: Organization(),
    plugins: [],
    processingIssues: 0,
    relayPiiConfig: '',
    subjectTemplate: '',
    ...params,
  };
}
