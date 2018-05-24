package io.noetl.config

import pureconfig.loadConfig

object AppConfig {
  final case class Http(interface: String, port: Int)
  final case class Countries(url: String)
  final case class Weather(url: String, appid: String)
  final case class Endpoints(example: String, countries: Countries, weather: Weather)
  final case class Config(http: Http, endpoints: Endpoints, logToFile: Boolean, defaultCity: String)

  val config: Config = loadConfig[Config] match {
    case Right(conf) =>
      conf

    case Left(err) =>
      Console.err.println(err.toList)
      throw new Exception(err.head.description)
  }
}
