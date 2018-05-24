package io.noetl.model

import io.circe.{Decoder, Encoder}
import io.circe.generic.semiauto._
import io.circe.generic.auto._

final case class WeatherInfo(weather: List[Weather], main: MainInfo)
object WeatherInfo {
  implicit val decoder: Decoder[WeatherInfo] = deriveDecoder
  implicit val encoder: Encoder[WeatherInfo] = deriveEncoder
}

final case class MainInfo(
    grnd_level: Option[BigDecimal],
    humidity: BigDecimal,
    pressure: BigDecimal,
    sea_level: Option[BigDecimal],
    temp: BigDecimal,
    temp_min: BigDecimal,
    temp_max: BigDecimal
)

final case class Weather(main: String, description: String, id: Int, icon: String)
