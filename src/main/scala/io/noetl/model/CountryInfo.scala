package io.noetl.model

import io.circe.{Decoder, Encoder}
import io.circe.generic.semiauto._
import io.circe.generic.auto._

final case class CountryInfo(
    name: String,
    population: Option[Double],
    area: Option[Double],
    gini: Option[Double],
    currencies: List[Currency],
    capital: String,
    subregion: Option[String],
    flag: Option[String]
)
object CountryInfo {
  implicit val decoder: Decoder[CountryInfo] = deriveDecoder
  implicit val encoder: Encoder[CountryInfo] = deriveEncoder
}

final case class Currency(code: String, symbol: String)
