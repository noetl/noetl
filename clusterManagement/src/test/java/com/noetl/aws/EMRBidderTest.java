package com.noetl.aws;

import com.noetl.pojos.clusterConfigs.EMRPremium;
import org.junit.Before;
import org.junit.Test;

import java.io.File;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

import static org.junit.Assert.assertEquals;

public class EMRBidderTest {

  private EMRBidder bidder;

  @Before
  public void setUp() throws Exception {
    String path = this.getClass().getResource("/spotPrices/sampleSpotPrice").getPath();
    File priceFile = new File(path);
    bidder = new EMRBidder(priceFile, "USD");
  }

  @Test
  public void testGetSpotForSize() throws Exception {
    EMRBid spotForSize = bidder.getSpotForSize("us-east", "linux", "m3.large");
    assertEquals("m3.large", spotForSize.getSize());
    assertEquals(0.0177 + EMRBidder.ACTUAL_BID_PREMIUM, spotForSize.getBidPriceBeforeRounding(), 1e-6);
  }

  @Test
  public void testBestBidByTier1() throws Exception {
    Collection<EMRPremium> tier = new ArrayList<>();
    tier.add(new EMRPremium("m3.large", 0.0186));   //orig: 0.0177
    tier.add(new EMRPremium("m3.xlarge", 0.0)); //orig: 0.0364

    EMRBid bestBid = bidder.bestBidByTier("us-east", "linux", tier);
    assertEquals("m3.large", bestBid.getSize());
    assertEquals(0.5177, bestBid.getBidPriceBeforeRounding(), 1e-6);
  }

  @Test
  public void testBestBidByTier2() throws Exception {
    Collection<EMRPremium> tier = new ArrayList<>();
    tier.add(new EMRPremium("m3.large", 0.0188));   //orig: 0.0177
    tier.add(new EMRPremium("m3.xlarge", 0.0)); //orig: 0.0364

    EMRBid bestBid = bidder.bestBidByTier("us-east", "linux", tier);
    assertEquals("m3.xlarge", bestBid.getSize());
    assertEquals(0.5364, bestBid.getBidPriceBeforeRounding(), 1e-6);
  }
}
