import {Fragment} from 'react';

import ExternalLink from 'sentry/components/links/externalLink';
import Link from 'sentry/components/links/link';
import {Layout, LayoutProps} from 'sentry/components/onboarding/gettingStartedDoc/layout';
import {ModuleProps} from 'sentry/components/onboarding/gettingStartedDoc/sdkDocumentation';
import {StepType} from 'sentry/components/onboarding/gettingStartedDoc/step';
import {t, tct} from 'sentry/locale';

interface StepProps {
  dsn: string;
  organizationSlug?: string;
  projectSlug?: string;
  sourcePackageRegistries?: ModuleProps['sourcePackageRegistries'];
}

// Configuration Start
const introduction = (
  <p>
    {tct(
      'Sentry for Java is a collection of modules provided by Sentry; it supports Java 1.8 and above. At its core, Sentry for Java provides a raw client for sending events to Sentry. If you use [strong:Spring Boot, Spring, Logback, or Log4j2], we recommend visiting our Sentry Java documentation for installation instructions.',
      {
        strong: <strong />,
        link: <ExternalLink href="https://docs.sentry.io/platforms/java/" />,
      }
    )}
  </p>
);

export const steps = ({
  dsn,
  sourcePackageRegistries,
  projectSlug,
  organizationSlug,
}: StepProps): LayoutProps['steps'] => [
  {
    type: StepType.INSTALL,
    description: t('Install the SDK via Gradle, Maven, or SBT:'),
    configurations: [
      {
        description: (
          <p>
            {tct(
              'To see source context in Sentry, you have to generate an auth token by visiting the [link:Organization Auth Tokens] settings. You can then set the token as an environment variable that is used by the build plugins.',
              {
                link: <Link to="/settings/auth-tokens/" />,
              }
            )}
          </p>
        ),
        language: 'bash',
        code: `
SENTRY_AUTH_TOKEN=___ORG_AUTH_TOKEN___
            `,
      },
      {
        description: <h5>{t('Gradle')}</h5>,
        configurations: [
          {
            language: 'groovy',
            partialLoading: sourcePackageRegistries?.isLoading,
            description: (
              <p>
                {tct(
                  'The [link:Sentry Gradle Plugin] automatically installs the Sentry SDK as well as available integrations for your dependencies. Add the following to your [code:build.gradle] file:',
                  {
                    code: <code />,
                    link: (
                      <ExternalLink href="https://github.com/getsentry/sentry-android-gradle-plugin" />
                    ),
                  }
                )}
              </p>
            ),
            code: `
buildscript {
  repositories {
    mavenCentral()
  }
}

plugins {
  id "io.sentry.jvm.gradle" version "${
    sourcePackageRegistries?.isLoading
      ? t('\u2026loading')
      : sourcePackageRegistries?.data?.['sentry.java.android.gradle-plugin']?.version ??
        '3.12.0'
  }"
}

sentry {
  // Generates a JVM (Java, Kotlin, etc.) source bundle and uploads your source code to Sentry.
  // This enables source context, allowing you to see your source
  // code as part of your stack traces in Sentry.
  includeSourceContext = true

  org = "${organizationSlug}"
  projectName = "${projectSlug}"
  authToken = System.getenv("SENTRY_AUTH_TOKEN")
}
        `,
          },
        ],
      },
      {
        description: <h5>{t('Maven')}</h5>,
        configurations: [
          {
            language: 'xml',
            partialLoading: sourcePackageRegistries?.isLoading,
            description: (
              <p>
                {tct('For Maven, add to your [code:pom.xml] file:', {code: <code />})}
              </p>
            ),
            code: `
<dependency>
  <groupId>io.sentry</groupId>
  <artifactId>sentry</artifactId>
  <version>${
    sourcePackageRegistries?.isLoading
      ? t('\u2026loading')
      : sourcePackageRegistries?.data?.['sentry.java']?.version ?? '6.27.0'
  }</version>
</dependency>
            `,
          },
          {
            language: 'xml',
            partialLoading: sourcePackageRegistries?.isLoading,
            description: t(
              'To upload your source code to Sentry so it can be shown in stack traces, use our Maven plugin.'
            ),
            code: `
<build>
  <plugins>
    <plugin>
      <groupId>io.sentry</groupId>
      <artifactId>sentry-maven-plugin</artifactId>
      <version>${
        sourcePackageRegistries?.isLoading
          ? t('\u2026loading')
          : sourcePackageRegistries?.data?.['sentry.java.mavenplugin']?.version ?? '0.0.4'
      }</version>
      <configuration>
      <!-- for showing output of sentry-cli -->
      <debugSentryCli>true</debugSentryCli>

      <org>${organizationSlug}</org>

      <project>${projectSlug}</project>

      <!-- in case you're self hosting, provide the URL here -->
      <!--<url>http://localhost:8000/</url>-->

      <!-- provide your auth token via SENTRY_AUTH_TOKEN environment variable -->
      <authToken>\${env.SENTRY_AUTH_TOKEN}</authToken>
      </configuration>
      <executions>
        <execution>
            <phase>generate-resources</phase>
            <goals>
                <goal>uploadSourceBundle</goal>
            </goals>
        </execution>
      </executions>
    </plugin>
  </plugins>
...
</build>
            `,
          },
        ],
      },
      {
        description: <h5>{t('SBT')}</h5>,
        configurations: [
          {
            description: <p>{tct('For [strong:SBT]:', {strong: <strong />})}</p>,
            language: 'scala',
            partialLoading: sourcePackageRegistries?.isLoading,
            code: `libraryDependencies += "io.sentry" % "sentry" % "${
              sourcePackageRegistries?.isLoading
                ? t('\u2026loading')
                : sourcePackageRegistries?.data?.['sentry.java']?.version ?? '6.27.0'
            }"`,
          },
        ],
      },
    ],
    additionalInfo: (
      <p>
        {tct(
          'To upload your source code to Sentry so it can be shown in stack traces, please refer to [link:Manually Uploading Source Context].',
          {
            link: (
              <ExternalLink href="https://docs.sentry.io/platforms/java/source-context/" />
            ),
          }
        )}
      </p>
    ),
  },
  {
    type: StepType.CONFIGURE,
    description: t(
      "Configure Sentry as soon as possible in your application's lifecycle:"
    ),
    configurations: [
      {
        language: 'java',
        code: `
import io.sentry.Sentry;

Sentry.init(options -> {
  options.setDsn("${dsn}");
  // Set tracesSampleRate to 1.0 to capture 100% of transactions for performance monitoring.
  // We recommend adjusting this value in production.
  options.setTracesSampleRate(1.0);
  // When first trying Sentry it's good to see what the SDK is doing:
  options.setDebug(true);
});
      `,
      },
    ],
  },
  {
    type: StepType.VERIFY,
    description: (
      <p>
        {tct(
          'Trigger your first event from your development environment by intentionally creating an error with the [code:Sentry#captureException] method, to test that everything is working:',
          {code: <code />}
        )}
      </p>
    ),
    configurations: [
      {
        language: 'java',
        code: `
import java.lang.Exception;
import io.sentry.Sentry;

try {
  throw new Exception("This is a test.");
} catch (Exception e) {
  Sentry.captureException(e);
}
      `,
      },
    ],
    additionalInfo: (
      <Fragment>
        <p>
          {t(
            "If you're new to Sentry, use the email alert to access your account and complete a product tour."
          )}
        </p>
        <p>
          {t(
            "If you're an existing user and have disabled alerts, you won't receive this email."
          )}
        </p>
      </Fragment>
    ),
  },
];

export const nextSteps = [
  {
    id: 'examples',
    name: t('Examples'),
    description: t('Check out our sample applications.'),
    link: 'https://github.com/getsentry/sentry-java/tree/main/sentry-samples',
  },
  {
    id: 'performance-monitoring',
    name: t('Performance Monitoring'),
    description: t(
      'Stay ahead of latency issues and trace every slow transaction to a poor-performing API call or database query.'
    ),
    link: 'https://docs.sentry.io/platforms/java/performance/',
  },
];
// Configuration End

export function GettingStartedWithJava({
  dsn,
  sourcePackageRegistries,
  projectSlug,
  organization,
  ...props
}: ModuleProps) {
  const nextStepDocs = [...nextSteps];

  return (
    <Layout
      steps={steps({
        dsn,
        sourcePackageRegistries,
        projectSlug: projectSlug ?? '___PROJECT_SLUG___',
        organizationSlug: organization?.slug ?? '___ORG_SLUG___',
      })}
      nextSteps={nextStepDocs}
      introduction={introduction}
      {...props}
    />
  );
}

export default GettingStartedWithJava;
