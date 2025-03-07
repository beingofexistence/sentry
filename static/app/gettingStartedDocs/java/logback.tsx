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
      'The sentry-logback library provides Logback support for Sentry using an [link:Appender] that sends logged exceptions to Sentry.',
      {
        link: (
          <ExternalLink href="https://logback.qos.ch/apidocs/ch/qos/logback/core/Appender.html" />
        ),
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
    description: t(
      "Install Sentry's integration with Logback using either Maven or Gradle:"
    ),
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
            language: 'groovy',
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
            code: `
<dependency>
  <groupId>io.sentry</groupId>
  <artifactId>sentry-logback</artifactId>
  <version>${
    sourcePackageRegistries?.isLoading
      ? t('\u2026loading')
      : sourcePackageRegistries?.data?.['sentry.java.logback']?.version ?? '6.27.0'
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
    ],
    additionalInfo: (
      <p>
        {tct('For other dependency managers see the [link:central Maven repository].', {
          link: (
            <ExternalLink href="https://search.maven.org/artifact/io.sentry/sentry-logback" />
          ),
        })}
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
        language: 'xml',
        description: t(
          'The following example configures a ConsoleAppender that logs to standard out at the INFO level, and a SentryAppender that logs to the Sentry server at the ERROR level. This only an example of a non-Sentry appender set to a different logging threshold, similar to what you may already have in your project.'
        ),
        code: `
<configuration>
  <!-- Configure the Console appender -->
  <appender name="Console" class="ch.qos.logback.core.ConsoleAppender">
    <encoder>
      <pattern>%d{HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n</pattern>
    </encoder>
  </appender>

  <!-- Configure the Sentry appender, overriding the logging threshold to the WARN level -->
  <appender name="Sentry" class="io.sentry.logback.SentryAppender">
    <options>
      <dsn>${dsn}</dsn>
    </options>
  </appender>

  <!-- Enable the Console and Sentry appenders, Console is provided as an example
  of a non-Sentry logger that is set to a different logging threshold -->
  <root level="INFO">
    <appender-ref ref="Console" />
    <appender-ref ref="Sentry" />
  </root>
</configuration>
        `,
        additionalInfo: (
          <p>
            {tct(
              "You'll also need to configure your DSN (client key) if it's not already in the [code:logback.xml] configuration. Learn more in [link:our documentation for DSN configuration].",
              {
                code: <code />,
                link: (
                  <ExternalLink href="https://docs.sentry.io/platforms/java/guides/logback/#dsn-configuration/" />
                ),
              }
            )}
          </p>
        ),
      },
      {
        description: (
          <p>
            {tct(
              "Next, you'll need to set your log levels, as illustrated here. You can learn more about [link:configuring log levels] in our documentation.",
              {
                link: (
                  <ExternalLink href="https://docs.sentry.io/platforms/java/guides/logback/#minimum-log-level/" />
                ),
              }
            )}
          </p>
        ),
        configurations: [
          {
            language: 'xml',
            code: `
<appender name="Sentry" class="io.sentry.logback.SentryAppender">
  <options>
    <dsn>${dsn}</dsn>
  </options>
  <!-- Optionally change minimum Event level. Default for Events is ERROR -->
  <minimumEventLevel>WARN</minimumEventLevel>
  <!-- Optionally change minimum Breadcrumbs level. Default for Breadcrumbs is INFO -->
  <minimumBreadcrumbLevel>DEBUG</minimumBreadcrumbLevel>
</appender>
          `,
          },
        ],
      },
    ],
  },
  {
    type: StepType.VERIFY,
    description: t(
      'Last, create an intentional error, so you can test that everything is working:'
    ),
    configurations: [
      {
        description: <h5>Java</h5>,
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
      {
        description: <h5>Kotlin</h5>,
        language: 'java',
        code: `
import java.lang.Exception
import io.sentry.Sentry

try {
  throw Exception("This is a test.")
} catch (e: Exception) {
  Sentry.captureException(e)
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
];
// Configuration End

export function GettingStartedWithLogBack({
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

export default GettingStartedWithLogBack;
