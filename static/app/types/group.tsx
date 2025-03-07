import type {SearchGroup} from 'sentry/components/smartSearchBar/types';
import type {PlatformKey} from 'sentry/data/platformCategories';
import type {FieldKind} from 'sentry/utils/fields';

import type {Actor, TimeseriesValue} from './core';
import type {Event, EventMetadata, EventOrGroupType, Level} from './event';
import type {Commit, PullRequest, Repository} from './integrations';
import type {Team} from './organization';
import type {Project} from './project';
import type {AvatarUser, User} from './user';

export type EntryData = Record<string, any | Array<any>>;

/**
 * Saved issues searches
 */
export type RecentSearch = {
  dateCreated: string;
  id: string;
  lastSeen: string;
  organizationId: string;
  query: string;
  type: SavedSearchType;
};

// XXX: Deprecated Sentry 9 attributes are not included here.
export type SavedSearch = {
  dateCreated: string;
  id: string;
  isGlobal: boolean;
  isPinned: boolean;
  name: string;
  query: string;
  sort: string;
  type: SavedSearchType;
  visibility: SavedSearchVisibility;
};

export enum SavedSearchVisibility {
  ORGANIZATION = 'organization',
  OWNER = 'owner',
  OWNER_PINNED = 'owner_pinned',
}

export enum SavedSearchType {
  ISSUE = 0,
  EVENT = 1,
  SESSION = 2,
  REPLAY = 3,
}

export enum IssueCategory {
  PERFORMANCE = 'performance',
  ERROR = 'error',
  CRON = 'cron',
  PROFILE = 'profile',
}

export enum IssueType {
  // Error
  ERROR = 'error',

  // Performance
  PERFORMANCE_CONSECUTIVE_DB_QUERIES = 'performance_consecutive_db_queries',
  PERFORMANCE_CONSECUTIVE_HTTP = 'performance_consecutive_http',
  PERFORMANCE_FILE_IO_MAIN_THREAD = 'performance_file_io_main_thread',
  PERFORMANCE_DB_MAIN_THREAD = 'performance_db_main_thread',
  PERFORMANCE_N_PLUS_ONE_API_CALLS = 'performance_n_plus_one_api_calls',
  PERFORMANCE_N_PLUS_ONE_DB_QUERIES = 'performance_n_plus_one_db_queries',
  PERFORMANCE_SLOW_DB_QUERY = 'performance_slow_db_query',
  PERFORMANCE_RENDER_BLOCKING_ASSET = 'performance_render_blocking_asset_span',
  PERFORMANCE_UNCOMPRESSED_ASSET = 'performance_uncompressed_assets',
  PERFORMANCE_LARGE_HTTP_PAYLOAD = 'performance_large_http_payload',
  PERFORMANCE_HTTP_OVERHEAD = 'performance_http_overhead',
  PERFORMANCE_DURATION_REGRESSION = 'performance_duration_regression',

  // Profile
  PROFILE_FILE_IO_MAIN_THREAD = 'profile_file_io_main_thread',
  PROFILE_IMAGE_DECODE_MAIN_THREAD = 'profile_image_decode_main_thread',
  PROFILE_JSON_DECODE_MAIN_THREAD = 'profile_json_decode_main_thread',
  PROFILE_REGEX_MAIN_THREAD = 'profile_regex_main_thread',
}

export const getIssueTypeFromOccurenceType = (
  typeId: number | undefined
): IssueType | null => {
  const occurrenceTypeToIssueIdMap = {
    1001: IssueType.PERFORMANCE_SLOW_DB_QUERY,
    1004: IssueType.PERFORMANCE_RENDER_BLOCKING_ASSET,
    1006: IssueType.PERFORMANCE_N_PLUS_ONE_DB_QUERIES,
    1007: IssueType.PERFORMANCE_CONSECUTIVE_DB_QUERIES,
    1008: IssueType.PERFORMANCE_FILE_IO_MAIN_THREAD,
    1009: IssueType.PERFORMANCE_CONSECUTIVE_HTTP,
    1010: IssueType.PERFORMANCE_N_PLUS_ONE_API_CALLS,
    1012: IssueType.PERFORMANCE_UNCOMPRESSED_ASSET,
    1013: IssueType.PERFORMANCE_DB_MAIN_THREAD,
    1015: IssueType.PERFORMANCE_LARGE_HTTP_PAYLOAD,
    1016: IssueType.PERFORMANCE_HTTP_OVERHEAD,
  };
  if (!typeId) {
    return null;
  }
  return occurrenceTypeToIssueIdMap[typeId] ?? null;
};

// endpoint: /api/0/issues/:issueId/attachments/?limit=50
export type IssueAttachment = {
  dateCreated: string;
  event_id: string;
  headers: object;
  id: string;
  mimetype: string;
  name: string;
  sha1: string;
  size: number;
  type: string;
};

// endpoint: /api/0/projects/:orgSlug/:projSlug/events/:eventId/attachments/
export type EventAttachment = IssueAttachment;

/**
 * Issue Tags
 */
export type Tag = {
  key: string;
  name: string;

  isInput?: boolean;

  kind?: FieldKind;
  /**
   * How many values should be suggested in autocomplete.
   * Overrides SmartSearchBar's `maxSearchItems` prop.
   */
  maxSuggestedValues?: number;
  predefined?: boolean;
  totalValues?: number;
  /**
   * Usually values are strings, but a predefined tag can define its SearchGroups
   */
  values?: string[] | SearchGroup[];
};

export type TagCollection = Record<string, Tag>;

export type TagValue = {
  count: number;
  firstSeen: string;
  lastSeen: string;
  name: string;
  value: string;
  email?: string;
  identifier?: string;
  ipAddress?: string;
  key?: string;
  query?: string;
  username?: string;
} & AvatarUser;

type Topvalue = {
  count: number;
  firstSeen: string;
  key: string;
  lastSeen: string;
  name: string;
  value: string;
  // Might not actually exist.
  query?: string;
  readable?: string;
};

export type TagWithTopValues = {
  key: string;
  name: string;
  topValues: Array<Topvalue>;
  totalValues: number;
  uniqueValues: number;
  canDelete?: boolean;
};

/**
 * Inbox, issue owners and Activity
 */
export type InboxReasonDetails = {
  count?: number | null;
  until?: string | null;
  user_count?: number | null;
  user_window?: number | null;
  window?: number | null;
};

export const enum GroupInboxReason {
  NEW = 0,
  UNIGNORED = 1,
  REGRESSION = 2,
  MANUAL = 3,
  REPROCESSED = 4,
  ESCALATING = 5,
  ONGOING = 6,
}

export type InboxDetails = {
  date_added?: string;
  reason?: GroupInboxReason;
  reason_details?: InboxReasonDetails | null;
};

export type SuggestedOwnerReason =
  | 'suspectCommit'
  | 'ownershipRule'
  | 'projectOwnership'
  // TODO: codeowners may no longer exist
  | 'codeowners';

// Received from the backend to denote suggested owners of an issue
export type SuggestedOwner = {
  date_added: string;
  owner: string;
  type: SuggestedOwnerReason;
};

export interface ParsedOwnershipRule {
  matcher: {pattern: string; type: string};
  owners: Actor[];
}

export type IssueOwnership = {
  autoAssignment:
    | 'Auto Assign to Suspect Commits'
    | 'Auto Assign to Issue Owner'
    | 'Turn off Auto-Assignment';
  codeownersAutoSync: boolean;
  dateCreated: string | null;
  fallthrough: boolean;
  isActive: boolean;
  lastUpdated: string | null;
  raw: string | null;
  schema?: {rules: ParsedOwnershipRule[]; version: number};
};

export enum GroupActivityType {
  NOTE = 'note',
  SET_RESOLVED = 'set_resolved',
  SET_RESOLVED_BY_AGE = 'set_resolved_by_age',
  SET_RESOLVED_IN_RELEASE = 'set_resolved_in_release',
  SET_RESOLVED_IN_COMMIT = 'set_resolved_in_commit',
  SET_RESOLVED_IN_PULL_REQUEST = 'set_resolved_in_pull_request',
  SET_UNRESOLVED = 'set_unresolved',
  SET_IGNORED = 'set_ignored',
  SET_PUBLIC = 'set_public',
  SET_PRIVATE = 'set_private',
  SET_REGRESSION = 'set_regression',
  CREATE_ISSUE = 'create_issue',
  UNMERGE_SOURCE = 'unmerge_source',
  UNMERGE_DESTINATION = 'unmerge_destination',
  FIRST_SEEN = 'first_seen',
  ASSIGNED = 'assigned',
  UNASSIGNED = 'unassigned',
  MERGE = 'merge',
  REPROCESS = 'reprocess',
  MARK_REVIEWED = 'mark_reviewed',
  AUTO_SET_ONGOING = 'auto_set_ongoing',
  SET_ESCALATING = 'set_escalating',
}

interface GroupActivityBase {
  dateCreated: string;
  id: string;
  project: Project;
  assignee?: string;
  issue?: Group;
  user?: null | User;
}

interface GroupActivityNote extends GroupActivityBase {
  data: {
    text: string;
  };
  type: GroupActivityType.NOTE;
}

interface GroupActivitySetResolved extends GroupActivityBase {
  data: Record<string, any>;
  type: GroupActivityType.SET_RESOLVED;
}

interface GroupActivitySetUnresolved extends GroupActivityBase {
  data: Record<string, any>;
  type: GroupActivityType.SET_UNRESOLVED;
}

interface GroupActivitySetPublic extends GroupActivityBase {
  data: Record<string, any>;
  type: GroupActivityType.SET_PUBLIC;
}

interface GroupActivitySetPrivate extends GroupActivityBase {
  data: Record<string, any>;
  type: GroupActivityType.SET_PRIVATE;
}

interface GroupActivitySetByAge extends GroupActivityBase {
  data: Record<string, any>;
  type: GroupActivityType.SET_RESOLVED_BY_AGE;
}

interface GroupActivityUnassigned extends GroupActivityBase {
  data: Record<string, any>;
  type: GroupActivityType.UNASSIGNED;
}

interface GroupActivityFirstSeen extends GroupActivityBase {
  data: Record<string, any>;
  type: GroupActivityType.FIRST_SEEN;
}

interface GroupActivityMarkReviewed extends GroupActivityBase {
  data: Record<string, any>;
  type: GroupActivityType.MARK_REVIEWED;
}

interface GroupActivityRegression extends GroupActivityBase {
  data: {
    /**
     * True if the project is using semver to decide if the event is a regression.
     * Available when the issue was resolved in a release.
     */
    follows_semver?: boolean;
    /**
     * The version that the issue was previously resolved in.
     * Available when the issue was resolved in a release.
     */
    resolved_in_version?: string;
    version?: string;
  };
  type: GroupActivityType.SET_REGRESSION;
}

export interface GroupActivitySetByResolvedInNextSemverRelease extends GroupActivityBase {
  data: {
    // Set for semver releases
    current_release_version: string;
  };
  type: GroupActivityType.SET_RESOLVED_IN_RELEASE;
}

export interface GroupActivitySetByResolvedInRelease extends GroupActivityBase {
  data: {
    version?: string;
  };
  type: GroupActivityType.SET_RESOLVED_IN_RELEASE;
}

interface GroupActivitySetByResolvedInCommit extends GroupActivityBase {
  data: {
    commit?: Commit;
  };
  type: GroupActivityType.SET_RESOLVED_IN_COMMIT;
}

interface GroupActivitySetByResolvedInPullRequest extends GroupActivityBase {
  data: {
    pullRequest?: PullRequest;
  };
  type: GroupActivityType.SET_RESOLVED_IN_PULL_REQUEST;
}

export interface GroupActivitySetIgnored extends GroupActivityBase {
  data: {
    ignoreCount?: number;
    ignoreDuration?: number;
    ignoreUntil?: string;
    /** Archived until escalating */
    ignoreUntilEscalating?: boolean;
    ignoreUserCount?: number;
    ignoreUserWindow?: number;
    ignoreWindow?: number;
  };
  type: GroupActivityType.SET_IGNORED;
}

export interface GroupActivityReprocess extends GroupActivityBase {
  data: {
    eventCount: number;
    newGroupId: number;
    oldGroupId: number;
  };
  type: GroupActivityType.REPROCESS;
}

interface GroupActivityUnmergeDestination extends GroupActivityBase {
  data: {
    fingerprints: Array<string>;
    source?: {
      id: string;
      shortId: string;
    };
  };
  type: GroupActivityType.UNMERGE_DESTINATION;
}

interface GroupActivityUnmergeSource extends GroupActivityBase {
  data: {
    fingerprints: Array<string>;
    destination?: {
      id: string;
      shortId: string;
    };
  };
  type: GroupActivityType.UNMERGE_SOURCE;
}

interface GroupActivityMerge extends GroupActivityBase {
  data: {
    issues: Array<any>;
  };
  type: GroupActivityType.MERGE;
}

interface GroupActivityAutoSetOngoing extends GroupActivityBase {
  data: {
    afterDays?: number;
  };
  type: GroupActivityType.AUTO_SET_ONGOING;
}

export interface GroupActivitySetEscalating extends GroupActivityBase {
  data: {
    expired_snooze?: {
      count: number | null;
      until: Date | null;
      user_count: number | null;
      user_window: number | null;
      window: number | null;
    };
    forecast?: number;
  };
  type: GroupActivityType.SET_ESCALATING;
}

export interface GroupActivityAssigned extends GroupActivityBase {
  data: {
    assignee: string;
    assigneeType: string;
    user: Team | User;
    assigneeEmail?: string;
    /**
     * If the user was assigned via an integration
     */
    integration?: 'projectOwnership' | 'codeowners' | 'slack' | 'msteams';
    /** Codeowner or Project owner rule as a string */
    rule?: string;
  };
  type: GroupActivityType.ASSIGNED;
}

export interface GroupActivityCreateIssue extends GroupActivityBase {
  data: {
    location: string;
    provider: string;
    title: string;
  };
  type: GroupActivityType.CREATE_ISSUE;
}

export type GroupActivity =
  | GroupActivityNote
  | GroupActivitySetResolved
  | GroupActivitySetUnresolved
  | GroupActivitySetIgnored
  | GroupActivitySetByAge
  | GroupActivitySetByResolvedInRelease
  | GroupActivitySetByResolvedInNextSemverRelease
  | GroupActivitySetByResolvedInCommit
  | GroupActivitySetByResolvedInPullRequest
  | GroupActivityFirstSeen
  | GroupActivityMerge
  | GroupActivityReprocess
  | GroupActivityUnassigned
  | GroupActivityMarkReviewed
  | GroupActivityUnmergeDestination
  | GroupActivitySetPublic
  | GroupActivitySetPrivate
  | GroupActivityRegression
  | GroupActivityUnmergeSource
  | GroupActivityAssigned
  | GroupActivityCreateIssue
  | GroupActivityAutoSetOngoing
  | GroupActivitySetEscalating;

export type Activity = GroupActivity;

interface GroupFiltered {
  count: string;
  firstSeen: string;
  lastSeen: string;
  stats: Record<string, TimeseriesValue[]>;
  userCount: number;
}

export interface GroupStats extends GroupFiltered {
  filtered: GroupFiltered | null;
  id: string;
  // for issue alert previews, the last time a group triggered a rule
  lastTriggered?: string;
  lifetime?: GroupFiltered;
  sessionCount?: string | null;
}

export interface IgnoredStatusDetails {
  actor?: AvatarUser;
  ignoreCount?: number;
  // Sent in requests. ignoreUntil is used in responses.
  ignoreDuration?: number;
  ignoreUntil?: string;
  ignoreUntilEscalating?: boolean;
  ignoreUserCount?: number;
  ignoreUserWindow?: number;
  ignoreWindow?: number;
}
export interface ResolvedStatusDetails {
  actor?: AvatarUser;
  autoResolved?: boolean;
  inCommit?: {
    commit?: string;
    dateCreated?: string;
    id?: string;
    repository?: string | Repository;
  };
  inNextRelease?: boolean;
  inRelease?: string;
  repository?: string;
}
interface ReprocessingStatusDetails {
  info: {
    dateCreated: string;
    totalEvents: number;
  } | null;
  pendingEvents: number;
}

/**
 * The payload sent when marking reviewed
 */
export interface MarkReviewed {
  inbox: false;
}
/**
 * The payload sent when updating a group's status
 */
export interface GroupStatusResolution {
  status: GroupStatus.RESOLVED | GroupStatus.UNRESOLVED | GroupStatus.IGNORED;
  statusDetails: ResolvedStatusDetails | IgnoredStatusDetails | {};
  substatus?: GroupSubstatus | null;
}

export const enum GroupStatus {
  RESOLVED = 'resolved',
  UNRESOLVED = 'unresolved',
  IGNORED = 'ignored',
  REPROCESSING = 'reprocessing',
}

export const enum GroupSubstatus {
  ARCHIVED_UNTIL_ESCALATING = 'archived_until_escalating',
  ARCHIVED_UNTIL_CONDITION_MET = 'archived_until_condition_met',
  ARCHIVED_FOREVER = 'archived_forever',
  ESCALATING = 'escalating',
  ONGOING = 'ongoing',
  REGRESSED = 'regressed',
  NEW = 'new',
}

// TODO(ts): incomplete
export interface BaseGroup {
  activity: GroupActivity[];
  annotations: string[];
  assignedTo: Actor | null;
  culprit: string;
  firstSeen: string;
  hasSeen: boolean;
  id: string;
  isBookmarked: boolean;
  isPublic: boolean;
  isSubscribed: boolean;
  isUnhandled: boolean;
  issueCategory: IssueCategory;
  issueType: IssueType;
  lastSeen: string;
  level: Level;
  logger: string | null;
  metadata: EventMetadata;
  numComments: number;
  participants: User[];
  permalink: string;
  platform: PlatformKey;
  pluginActions: any[]; // TODO(ts)
  pluginContexts: any[]; // TODO(ts)
  pluginIssues: any[]; // TODO(ts)
  project: Project;
  seenBy: User[];
  shareId: string;
  shortId: string;
  status: GroupStatus;
  statusDetails: IgnoredStatusDetails | ResolvedStatusDetails | ReprocessingStatusDetails;
  subscriptionDetails: {disabled?: boolean; reason?: string} | null;
  title: string;
  type: EventOrGroupType;
  userReportCount: number;
  inbox?: InboxDetails | null | false;
  latestEvent?: Event;
  owners?: SuggestedOwner[] | null;
  substatus?: GroupSubstatus | null;
}

export interface GroupReprocessing extends BaseGroup, GroupStats {
  status: GroupStatus.REPROCESSING;
  statusDetails: ReprocessingStatusDetails;
}

export interface GroupResolved extends BaseGroup, GroupStats {
  status: GroupStatus.RESOLVED;
  statusDetails: ResolvedStatusDetails;
}

export interface GroupIgnored extends BaseGroup, GroupStats {
  status: GroupStatus.IGNORED;
  statusDetails: IgnoredStatusDetails;
}

export interface GroupUnresolved extends BaseGroup, GroupStats {
  status: GroupStatus.UNRESOLVED;
  statusDetails: {};
}

export type Group = GroupUnresolved | GroupResolved | GroupIgnored | GroupReprocessing;

export interface GroupTombstone {
  actor: AvatarUser;
  culprit: string;
  id: string;
  level: Level;
  metadata: EventMetadata;
  type: EventOrGroupType;
  title?: string;
}
export interface GroupTombstoneHelper extends GroupTombstone {
  isTombstone: true;
}

export type ProcessingIssueItem = {
  checksum: string;
  data: {
    // TODO(ts) This type is likely incomplete, but this is what
    // project processing issues settings uses.
    _scope: string;
    image_arch: string;
    image_path: string;
    image_uuid: string;
    dist?: string;
    release?: string;
  };
  id: string;
  lastSeen: string;
  numEvents: number;
  type: string;
};

export type ProcessingIssue = {
  hasIssues: boolean;
  hasMoreResolveableIssues: boolean;
  issuesProcessing: number;
  lastSeen: string;
  numIssues: number;
  project: string;
  resolveableIssues: number;
  signedLink: string;
  issues?: ProcessingIssueItem[];
};

/**
 * Datascrubbing
 */
export type Meta = {
  chunks: Array<ChunkType>;
  err: Array<MetaError>;
  len: number;
  rem: Array<MetaRemark>;
};

export type MetaError = string | [string, any];
export type MetaRemark = Array<string | number>;

export type ChunkType = {
  rule_id: string | number;
  text: string;
  type: string;
  remark?: string | number;
};

/**
 * User Feedback
 */
export type UserReport = {
  comments: string;
  dateCreated: string;
  email: string;
  event: {eventID: string; id: string};
  eventID: string;
  id: string;
  issue: Group;
  name: string;
  user: User;
};

export type KeyValueListDataItem = {
  key: string;
  subject: string;
  actionButton?: React.ReactNode;
  isContextData?: boolean;
  isMultiValue?: boolean;
  meta?: Meta;
  subjectDataTestId?: string;
  subjectIcon?: React.ReactNode;
  value?: React.ReactNode;
};

export type KeyValueListData = KeyValueListDataItem[];

// Response from ShortIdLookupEndpoint
// /organizations/${orgId}/shortids/${query}/
export type ShortIdResponse = {
  group: Group;
  groupId: string;
  organizationSlug: string;
  projectSlug: string;
  shortId: string;
};

/**
 * Note used in Group Activity and Alerts for users to comment
 */
export type Note = {
  /**
   * Array of [id, display string] tuples used for @-mentions
   */
  mentions: [string, string][];

  /**
   * Note contents (markdown allowed)
   */
  text: string;
};
