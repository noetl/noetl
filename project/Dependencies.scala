import sbt._

object  Dependencies {
  val akkaVersion                = "2.4.20"
  val akkaHttpVersion            = "10.0.11"
  val circeVersion               = "0.9.0"
  val akkaCirceVersion           = "1.19.0"
  val scalacticVersion           = "3.0.5"
  val scalaTestVersion           = "3.0.5"
  val scalaLoggingVersion        = "3.9.0"
  val logbackVesrion             = "1.2.3"
  val configVesrion              = "1.3.2"
  val timeVersion                = "2.18.0"
  val monixVersion               = "3.0.0-M3"
  val pureConfVersion            = "0.9.0"
  val httpClientVersion          = "4.5.3"
  val httpAsyncClientVersion     = "4.1.3"


  lazy val projectResolvers = Seq.empty
  lazy val dependencies = testDependencies ++ rootDependencies


  lazy val testDependencies = Seq (
    "org.scalatest"              %% "scalatest"             % scalaTestVersion % Test,
    "com.typesafe.akka"          %% "akka-http-testkit"     % akkaHttpVersion  % Test
  )

  lazy val rootDependencies = Seq(
    "org.scalactic"              %% "scalactic"             % scalacticVersion,
    "com.typesafe.akka"          %% "akka-http"             % akkaHttpVersion,
    "io.monix"                   %% "monix"                 % monixVersion,
    "io.circe"                   %% "circe-core"            % circeVersion,
    "io.circe"                   %% "circe-generic"         % circeVersion,
    "io.circe"                   %% "circe-parser"          % circeVersion,
    "com.github.nscala-time"     %% "nscala-time"           % timeVersion,
    "com.typesafe.akka"          %% "akka-slf4j"            % akkaVersion,
    "com.typesafe.scala-logging" %% "scala-logging"         % scalaLoggingVersion,
    "ch.qos.logback"              % "logback-classic"       % logbackVesrion,
    "com.typesafe"                % "config"                % configVesrion,
    "com.github.pureconfig"      %% "pureconfig"            % pureConfVersion,
    "org.apache.httpcomponents"   % "httpclient"            % httpClientVersion,
    "org.apache.httpcomponents"   % "httpasyncclient"       % httpAsyncClientVersion
  )
}
