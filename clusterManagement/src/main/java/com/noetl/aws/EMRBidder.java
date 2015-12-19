package com.noetl.aws;

import com.noetl.parsers.JsonParser;
import com.noetl.pojos.clusterConfigs.EMRPremium;
import org.apache.log4j.Logger;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

public class EMRBidder {
  public static final double ACTUAL_BID_PREMIUM = 0.5;

  private final static Logger logger = Logger.getLogger(EMRBidder.class);
  private final String spotPriceURL;
  private final String currency;
  private final File spotPriceFile;

  public EMRBidder(String spotPriceURL, String currency) {
    this.spotPriceURL = spotPriceURL;
    this.spotPriceFile = null;
    this.currency = currency.toUpperCase();
  }

  public EMRBidder(File spotPriceFile, String currency) throws IOException {
    this.spotPriceURL = null;
    this.spotPriceFile = spotPriceFile;
    this.currency = currency.toUpperCase();
  }

  private Map<String, ?> getPriceJson() throws IOException {
    logger.info("Getting EMR spot prices...");
    if (spotPriceURL != null) {
      InputStream in = new URL(spotPriceURL).openStream();
      Map<String, ?> priceMap = JsonParser.toMap(in, 9, 1);
      in.close();
      return priceMap;
    } else {
      return JsonParser.toMap(new FileInputStream(spotPriceFile), 9, 1);
    }
  }

  public EMRBid getSpotForSize(String regionName, String operationSystem, String size) throws IOException {
    Map<String, String> priceBySize = getSpotPricesBySize(regionName, operationSystem);
    String spotPriceString = priceBySize.get(size);
    Double spotPrice = Double.valueOf(spotPriceString);
    double bidPrice = spotPrice + ACTUAL_BID_PREMIUM;
    logger.info(String.format("Price for size '%s': Spot @ %s, Bid @ %s", size, spotPrice, bidPrice));
    return new EMRBid(size, bidPrice);
  }

  public EMRBid bestBidByTier(String regionName, String operationSystem, Collection<EMRPremium> premiumsMap) throws IOException {
    Map<String, String> priceBySize = getSpotPricesBySize(regionName, operationSystem);

    String cheapestSize = "";
    Double cheapestBid = Double.POSITIVE_INFINITY;
    Double actualBid = 0.0;

    logger.info("Spot prices for wanted sizes:");
    for (EMRPremium sizePremium : premiumsMap) {
      String size = sizePremium.getSize();
      Double premiumPrice = sizePremium.getPremium();

      String spotPriceString = priceBySize.get(size);
      Double spotPrice = Double.valueOf(spotPriceString);
      double bidPrice = premiumPrice + spotPrice;
      logger.info(String.format("Size: '%s', Spot @ %s, Premium @ %s, Bid @ %s", size, spotPrice, premiumPrice, bidPrice));

      if (cheapestBid > bidPrice) {
        cheapestSize = size;
        cheapestBid = bidPrice;
        actualBid = spotPrice + ACTUAL_BID_PREMIUM;
      }
    }
    logger.info(String.format("We are bidding the size '%s' @ price %s for your tier.", cheapestSize, actualBid));
    return new EMRBid(cheapestSize, actualBid);
  }

  private Map<String, String> getSpotPricesBySize(String regionName, String operationSystem) throws IOException {
    ArrayList<Map<String, ?>> pricesByType = getSpotPricesWithTypes(regionName);

    Map<String, String> priceBySize = new HashMap<>();
    for (Map<String, ?> pricesForEachType : pricesByType) {
      ArrayList<Map<String, ?>> sizePrices = (ArrayList<Map<String, ?>>) pricesForEachType.get("sizes");
      for (Map<String, ?> sizePrice : sizePrices) {
        for (Map<String, ?> valueColumn : (ArrayList<Map<String, ?>>) sizePrice.get("valueColumns")) {
          if (valueColumn.get("name").equals(operationSystem)) {
            priceBySize.put((String) sizePrice.get("size"),
              ((Map<String, String>) valueColumn.get("prices")).get(currency));
          }
        }
      }
    }
    logger.info(String.format("Fetched spot prices at region %s:\n%s", regionName, priceBySize));
    return priceBySize;
  }

  private ArrayList<Map<String, ?>> getSpotPricesWithTypes(String regionName) throws IOException {
    Map<String, ?> priceJson = getPriceJson();
    logger.info(String.format("Getting spot prices for %s...", regionName));
    Map<String, ?> configJson = (Map<String, ?>) priceJson.get("config");
    ArrayList<Map<String, ?>> regionsJson = (ArrayList<Map<String, ?>>) configJson.get("regions");

    for (Map<String, ?> regionJson : regionsJson) {
      if (regionJson.get("region").equals(regionName))
        return (ArrayList<Map<String, ?>>) regionJson.get("instanceTypes");
    }
    throw new RuntimeException("Cannot find spot price for the region " + regionName);
  }
}
