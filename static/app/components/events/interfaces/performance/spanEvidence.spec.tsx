import {initializeData} from 'sentry-test/performance/initializePerformanceData';
import {
  MockSpan,
  ProblemSpan,
  TransactionEventBuilder,
} from 'sentry-test/performance/utils';
import {render, screen} from 'sentry-test/reactTestingLibrary';

import {EntryType} from 'sentry/types';
import {projectDetectorSettingsId} from 'sentry/views/settings/projectPerformance/projectPerformance';

import {SpanEvidenceSection} from './spanEvidence';

const {organization, project} = initializeData();

describe('spanEvidence', () => {
  it('renders and highlights the correct data in the span evidence section', () => {
    const builder = new TransactionEventBuilder();
    builder.addSpan(
      new MockSpan({
        startTimestamp: 0,
        endTimestamp: 100,
        op: 'http',
        description: 'do a thing',
      })
    );

    builder.addSpan(
      new MockSpan({
        startTimestamp: 100,
        endTimestamp: 200,
        op: 'db',
        description: 'SELECT col FROM table',
      })
    );

    builder.addSpan(
      new MockSpan({
        startTimestamp: 200,
        endTimestamp: 300,
        op: 'db',
        description: 'SELECT col2 FROM table',
      })
    );

    builder.addSpan(
      new MockSpan({
        startTimestamp: 200,
        endTimestamp: 300,
        op: 'db',
        description: 'SELECT col3 FROM table',
      })
    );

    const parentProblemSpan = new MockSpan({
      startTimestamp: 300,
      endTimestamp: 600,
      op: 'db',
      description: 'connect',
      problemSpan: ProblemSpan.PARENT,
    });
    parentProblemSpan.addChild(
      {
        startTimestamp: 300,
        endTimestamp: 600,
        op: 'db',
        description: 'group me',
        problemSpan: ProblemSpan.OFFENDER,
      },
      9
    );

    builder.addSpan(parentProblemSpan);

    render(
      <SpanEvidenceSection
        event={builder.getEvent()}
        organization={organization}
        projectSlug={project.slug}
      />,
      {organization}
    );

    // Verify that the correct spans are hi-lighted on the span tree as affected spans
    const affectedSpan = screen.getByTestId('row-title-content-affected');
    expect(affectedSpan).toBeInTheDocument();
    expect(affectedSpan).toHaveTextContent('db — connect');
  });

  it('renders settings button for issue with configurable thresholds', () => {
    const event = TestStubs.Event({
      occurrence: {
        type: 1001,
      },
      entries: [
        {
          data: [],
          type: EntryType.SPANS,
        },
      ],
    });
    organization.features = ['project-performance-settings-admin'];

    render(
      <SpanEvidenceSection
        event={event}
        organization={organization}
        projectSlug={project.slug}
      />,
      {organization}
    );

    expect(screen.getByText('Span Evidence')).toBeInTheDocument();

    const settingsBtn = screen.getByTestId('span-evidence-settings-btn');
    expect(settingsBtn).toBeInTheDocument();
    expect(settingsBtn).toHaveAttribute(
      'href',
      `/settings/projects/project-slug/performance/#${projectDetectorSettingsId}`
    );
  });

  it('does not render settings button for issue without configurable thresholds', () => {
    const event = TestStubs.Event({
      occurrence: {
        type: 2003, // profile_json_decode_main_thread
      },
      entries: [
        {
          data: [],
          type: EntryType.SPANS,
        },
      ],
    });

    render(
      <SpanEvidenceSection
        event={event}
        organization={organization}
        projectSlug={project.slug}
      />,
      {organization}
    );

    expect(screen.getByText('Span Evidence')).toBeInTheDocument();

    const settingsBtn = screen.queryByTestId('span-evidence-settings-btn');
    expect(settingsBtn).not.toBeInTheDocument();
  });
});
