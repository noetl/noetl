package com.noetl.aws;

public class EMRBid {
  private final Double bidPriceBeforeRounding;
  private final String size;
  private final String bidPrice;

  public EMRBid(String size, Double bidPrice) {
    this.size = size;
    //round up to 2 decimal places
    this.bidPriceBeforeRounding = bidPrice;
    this.bidPrice = String.valueOf(Math.round(bidPrice * 100.0) / 100.0);
  }

  public String getSize() {
    return this.size;
  }

  public String getBidPrice() {
    return this.bidPrice;
  }

  public Double getBidPriceBeforeRounding() {
    return bidPriceBeforeRounding;
  }

  @Override
  public String toString() {
    return "EMRBid{" +
      "size='" + size + '\'' +
      ", bidPrice='" + bidPrice + '\'' +
      '}';
  }
}
