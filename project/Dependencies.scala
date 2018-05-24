import sbt._

object Dependencies {

  lazy val projectResolvers = Seq.empty
  lazy val dependencies = testDependencies ++ rootDependencies

  lazy val testDependencies = Seq (
    "org.scalatest"          %% "scalatest"             % "3.0.1" % Test,
    "com.typesafe.akka"      %% "akka-http-testkit"     % "10.0.11"  % Test
  )

  lazy val rootDependencies = Seq(
    "com.typesafe.akka"      %% "akka-http"             % "10.0.11",
    "de.heikoseeberger"      %% "akka-http-circe"       % "1.19.0",
    "io.monix"               %% "monix"                 % "3.0.0-M3",
    "io.circe"               %% "circe-core"            % "0.9.0",
    "io.circe"               %% "circe-generic"         % "0.9.0",
    "io.circe"               %% "circe-parser"          % "0.9.0",
    "com.github.nscala-time" %% "nscala-time"           % "2.18.0",
    "com.typesafe"            % "config"                % "1.3.2",
    "com.typesafe.akka"      %% "akka-slf4j"            % "2.4.20",
    "ch.qos.logback"          % "logback-classic"       % "1.2.3",
    "com.github.pureconfig"  %% "pureconfig"            % "0.9.0"
  )
}
