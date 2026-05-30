ASX_TICKERS = {
    "technology": [
        "WTC.AX", "TNE.AX", "XRO.AX", "ALU.AX", "CPU.AX",
        "MP1.AX", "APX.AX", "NXT.AX", "DSE.AX", "SXL.AX",
    ],
    "healthcare": [
        "CSL.AX", "RMD.AX", "COH.AX", "SHL.AX", "RHC.AX",
        "PME.AX", "PNV.AX", "NEU.AX", "IDX.AX", "EBR.AX",
    ],
    "financials": [
        "CBA.AX", "WBC.AX", "ANZ.AX", "NAB.AX", "MQG.AX",
        "SUN.AX", "IAG.AX", "BOQ.AX", "BEN.AX", "AMP.AX",
    ],
    "consumer": [
        "WOW.AX", "WES.AX", "COL.AX", "JBH.AX", "HVN.AX",
        "MTS.AX", "SUL.AX", "KGN.AX", "TPW.AX", "CCX.AX",
    ],
    "energy": [
        "WDS.AX", "STO.AX", "BHP.AX", "RIO.AX", "FMG.AX",
        "WHC.AX", "NHC.AX", "VEA.AX", "CVN.AX", "KAR.AX",
    ],
    "industrials": [
        "BXB.AX", "QAN.AX", "TCL.AX", "SYD.AX", "ALX.AX",
        "AZJ.AX", "DOW.AX", "NWS.AX", "SKI.AX", "AIA.AX",
    ],
}

ALL_TICKERS = [ticker for tickers in ASX_TICKERS.values() for ticker in tickers]
