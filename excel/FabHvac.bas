Attribute VB_Name = "FabHvac"
'==============================================================================
' FabHvac - cleanroom / chiller-plant worksheet functions (UDFs)
'
' Mirrors the Python package `fabhvac` (see README). Units are SI unless stated.
' Invalid inputs return #VALUE! (the Python side raises ValueError for the same cases).
'
' Psychrometrics: ASHRAE Handbook - Fundamentals (2017) ch.1 equations as implemented
' in PsychroLib 2.5.0 (MIT licence): saturation pressure eqn 5/6 (switching at the
' triple point 0.01 degC), humidity ratio eqn 20, enthalpy eqn 30, wet-bulb eqn 33/35,
' dew point by Newton-Raphson on ln(pws), wet bulb by bisection, tolerance 0.001 K.
'
' NEA MEES table and M&V heat balance: NEA web page and "Requirements and Guidelines
' on M&V for MEES" (retrieved 2026-10-02). NEA marks the table as indicative.
'
' Third-party notice: the psychrometric functions below port coefficients and algorithms
' from PsychroLib (https://github.com/psychrometrics/psychrolib), used under the MIT License:
'
' The MIT License (MIT)
'
' Copyright (c) 2018-2020 The PsychroLib Contributors.
'
' Permission is hereby granted, free of charge, to any person obtaining a copy
' of this software and associated documentation files (the "Software"), to deal
' in the Software without restriction, including without limitation the rights
' to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
' copies of the Software, and to permit persons to whom the Software is
' furnished to do so, subject to the following conditions:
'
' The above copyright notice and this permission notice shall be included in
' all copies or substantial portions of the Software.
'
' THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
' IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
' FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
' AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
' LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
' OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
' THE SOFTWARE.
'==============================================================================
Option Explicit

Public Const FH_RT_TO_KW As Double = 3.516853      ' NIST SP 811 B.9
Private Const ISO_EXPONENT As Double = 2.08
Private Const MIN_HUM_RATIO As Double = 0.0000001
Private Const PSY_TOL As Double = 0.001
Private Const MAX_ITER As Long = 100

'------------------------------------------------------------------ helpers
Private Function ErrValue() As Variant
    ErrValue = CVErr(xlErrValue)
End Function

Private Function CeilD(ByVal x As Double) As Double
    CeilD = -Int(-x)
End Function

Private Function MaxD(ByVal a As Double, ByVal b As Double) As Double
    If a > b Then MaxD = a Else MaxD = b
End Function

Private Function MinD(ByVal a As Double, ByVal b As Double) As Double
    If a < b Then MinD = a Else MinD = b
End Function

'------------------------------------------------------------------ ISO 14644-1
Public Function FH_ISO_CLASS_LIMIT(ByVal isoClass As Double, ByVal sizeUm As Double) As Variant
    If isoClass < 1 Or isoClass > 9 Or sizeUm < 0.1 Or sizeUm > 5 Then
        FH_ISO_CLASS_LIMIT = ErrValue(): Exit Function
    End If
    FH_ISO_CLASS_LIMIT = 10 ^ isoClass * (0.1 / sizeUm) ^ ISO_EXPONENT
End Function

Public Function FH_ISO_CLASS_FROM_CONC(ByVal concPerM3 As Double, ByVal sizeUm As Double) As Variant
    If concPerM3 <= 0 Or sizeUm < 0.1 Or sizeUm > 5 Then
        FH_ISO_CLASS_FROM_CONC = ErrValue(): Exit Function
    End If
    FH_ISO_CLASS_FROM_CONC = Log(concPerM3) / Log(10#) - ISO_EXPONENT * Log(0.1 / sizeUm) / Log(10#)
End Function

'------------------------------------------------------------------ airflow
Public Function FH_UD_AIRFLOW(ByVal faceVelocityMs As Double, ByVal filteredAreaM2 As Double) As Variant
    If faceVelocityMs <= 0 Or filteredAreaM2 <= 0 Then FH_UD_AIRFLOW = ErrValue(): Exit Function
    FH_UD_AIRFLOW = faceVelocityMs * filteredAreaM2
End Function

Public Function FH_FFU_COUNT(ByVal roomAreaM2 As Double, ByVal coverage As Double, ByVal ffuAreaM2 As Double) As Variant
    If coverage <= 0 Or coverage > 1 Or roomAreaM2 <= 0 Or ffuAreaM2 <= 0 Then
        FH_FFU_COUNT = ErrValue(): Exit Function
    End If
    FH_FFU_COUNT = CeilD(roomAreaM2 * coverage / ffuAreaM2 - 0.000000001)
End Function

Public Function FH_ACH(ByVal qM3s As Double, ByVal roomVolumeM3 As Double) As Variant
    If roomVolumeM3 <= 0 Then FH_ACH = ErrValue(): Exit Function
    FH_ACH = qM3s * 3600# / roomVolumeM3
End Function

Public Function FH_WM_CONC(ByVal genPerS As Double, ByVal qM3s As Double, ByVal eta As Double, _
                           Optional ByVal oaFraction As Double = 0, Optional ByVal cOut As Double = 0, _
                           Optional ByVal etaOA As Double = 0) As Variant
    If qM3s <= 0 Or eta < 0 Or eta >= 1 Or etaOA < 0 Or etaOA >= 1 Or oaFraction < 0 Or oaFraction > 1 _
       Or genPerS < 0 Or cOut < 0 Then
        FH_WM_CONC = ErrValue(): Exit Function
    End If
    Dim p As Double, pOA As Double
    p = 1 - eta: pOA = 1 - etaOA
    FH_WM_CONC = (genPerS / qM3s + p * oaFraction * pOA * cOut) / (1 - p * (1 - oaFraction))
End Function

Public Function FH_WM_REQUIRED_Q(ByVal genPerS As Double, ByVal cTarget As Double, ByVal eta As Double, _
                                 Optional ByVal oaFraction As Double = 0, Optional ByVal cOut As Double = 0, _
                                 Optional ByVal etaOA As Double = 0) As Variant
    If cTarget <= 0 Or eta < 0 Or eta >= 1 Or etaOA < 0 Or etaOA >= 1 Or oaFraction < 0 Or oaFraction > 1 _
       Or genPerS < 0 Or cOut < 0 Then
        FH_WM_REQUIRED_Q = ErrValue(): Exit Function
    End If
    Dim p As Double, pOA As Double, den As Double
    p = 1 - eta: pOA = 1 - etaOA
    den = cTarget * (1 - p * (1 - oaFraction)) - p * oaFraction * pOA * cOut
    If den <= 0 Then FH_WM_REQUIRED_Q = ErrValue(): Exit Function
    FH_WM_REQUIRED_Q = genPerS / den
End Function

'------------------------------------------------------------------ chiller plant
Public Function FH_KWRT_TO_KWEKWC(ByVal kwPerRt As Double) As Variant
    FH_KWRT_TO_KWEKWC = kwPerRt / FH_RT_TO_KW
End Function

Public Function FH_KWEKWC_TO_KWRT(ByVal kwePerKwc As Double) As Variant
    FH_KWEKWC_TO_KWRT = kwePerKwc * FH_RT_TO_KW
End Function

Public Function FH_COP(ByVal kwePerKwc As Double) As Variant
    If kwePerKwc <= 0 Then FH_COP = ErrValue(): Exit Function
    FH_COP = 1# / kwePerKwc
End Function

Public Function FH_PLANT_EFF(ByVal coolingKw As Double, ByVal chillerKw As Double, _
                             Optional ByVal chwPumpKw As Double = 0, Optional ByVal cdwPumpKw As Double = 0, _
                             Optional ByVal towerKw As Double = 0) As Variant
    If coolingKw <= 0 Or chillerKw < 0 Or chwPumpKw < 0 Or cdwPumpKw < 0 Or towerKw < 0 Then
        FH_PLANT_EFF = ErrValue(): Exit Function
    End If
    FH_PLANT_EFF = (chillerKw + chwPumpKw + cdwPumpKw + towerKw) / coolingKw
End Function

Public Function FH_MEES_LIMIT(ByVal chwsC As Double, Optional ByVal spaceCoolingNewBuilding As Boolean = False) As Variant
    If chwsC < 3 Then FH_MEES_LIMIT = ErrValue(): Exit Function
    Dim t As Long
    t = CLng(CeilD(Application.WorksheetFunction.Round(chwsC, 9)))
    If spaceCoolingNewBuilding Then
        Select Case t
            Case 3: FH_MEES_LIMIT = 0.191
            Case 4: FH_MEES_LIMIT = 0.188
            Case 5: FH_MEES_LIMIT = 0.185
            Case 6: FH_MEES_LIMIT = 0.182
            Case Else: FH_MEES_LIMIT = 0.179
        End Select
    Else
        Select Case t
            Case 3: FH_MEES_LIMIT = 0.203
            Case 4: FH_MEES_LIMIT = 0.2
            Case 5: FH_MEES_LIMIT = 0.197
            Case 6: FH_MEES_LIMIT = 0.194
            Case 7: FH_MEES_LIMIT = 0.191
            Case 8: FH_MEES_LIMIT = 0.188
            Case 9: FH_MEES_LIMIT = 0.185
            Case Else: FH_MEES_LIMIT = Application.WorksheetFunction.Round(0.185 - 0.003 * (t - 9), 6)
        End Select
    End If
End Function

Public Function FH_MEES_CHECK(ByVal kwePerKwc As Double, ByVal chwsC As Double, ByVal installedCapacityKw As Double, _
                              Optional ByVal spaceCoolingNewBuilding As Boolean = False) As Variant
    ' Same order as chiller.mees_check: negative efficiency or capacity is rejected before the scope test
    If kwePerKwc < 0 Or installedCapacityKw < 0 Then FH_MEES_CHECK = ErrValue(): Exit Function
    If installedCapacityKw < 1055 Or chwsC < 3 Then
        FH_MEES_CHECK = "OUT_OF_SCOPE": Exit Function
    End If
    If kwePerKwc <= FH_MEES_LIMIT(chwsC, spaceCoolingNewBuilding) Then
        FH_MEES_CHECK = "PASS"
    Else
        FH_MEES_CHECK = "FAIL"
    End If
End Function

Public Function FH_HEAT_BALANCE_PCT(ByVal coolingKw As Double, ByVal workInputKw As Double, ByVal heatRejectionKw As Double) As Variant
    If heatRejectionKw = 0 Then FH_HEAT_BALANCE_PCT = ErrValue(): Exit Function
    FH_HEAT_BALANCE_PCT = (coolingKw + workInputKw - heatRejectionKw) / heatRejectionKw * 100#
End Function

Public Function FH_MV_UNCERTAINTY(ByVal utSupplyK As Double, ByVal utReturnK As Double, ByVal dtChwK As Double, _
                                  ByVal uFlowPct As Double, ByVal uPowerPct As Double) As Variant
    If dtChwK <= 0 Then FH_MV_UNCERTAINTY = ErrValue(): Exit Function
    Dim dut As Double
    dut = Sqr(utSupplyK ^ 2 + utReturnK ^ 2) / dtChwK * 100#
    FH_MV_UNCERTAINTY = Sqr(dut ^ 2 + uFlowPct ^ 2 + uPowerPct ^ 2)
End Function

'------------------------------------------------------------------ cooling tower
Public Function FH_CT_RANGE(ByVal tWaterIn As Double, ByVal tWaterOut As Double) As Variant
    FH_CT_RANGE = tWaterIn - tWaterOut
End Function

Public Function FH_CT_APPROACH(ByVal tWaterOut As Double, ByVal tWetBulb As Double) As Variant
    FH_CT_APPROACH = tWaterOut - tWetBulb
End Function

Public Function FH_CT_EFFECTIVENESS(ByVal tWaterIn As Double, ByVal tWaterOut As Double, ByVal tWetBulb As Double) As Variant
    If tWaterIn - tWetBulb <= 0 Then FH_CT_EFFECTIVENESS = ErrValue(): Exit Function
    FH_CT_EFFECTIVENESS = (tWaterIn - tWaterOut) / (tWaterIn - tWetBulb)
End Function

'------------------------------------------------------------------ psychrometrics (SI)
Private Function PwsCore(ByVal tC As Double) As Double
    Dim t As Double, lnp As Double
    t = tC + 273.15
    If tC <= 0.01 Then
        lnp = -5674.5359 / t + 6.3925247 - 0.009677843 * t + 0.00000062215701 * t ^ 2 _
              + 0.0000000020747825 * t ^ 3 - 9.484024E-13 * t ^ 4 + 4.1635019 * Log(t)
    Else
        lnp = -5800.2206 / t + 1.3914993 - 0.048640239 * t + 0.000041764768 * t ^ 2 _
              - 0.000000014452093 * t ^ 3 + 6.5459673 * Log(t)
    End If
    PwsCore = Exp(lnp)
End Function

Private Function DLnPws(ByVal tC As Double) As Double
    Dim t As Double
    t = tC + 273.15
    If tC <= 0.01 Then
        DLnPws = 5674.5359 / t ^ 2 - 0.009677843 + 2 * 0.00000062215701 * t _
                 + 3 * 0.0000000020747825 * t ^ 2 - 4 * 9.484024E-13 * t ^ 3 + 4.1635019 / t
    Else
        DLnPws = 5800.2206 / t ^ 2 - 0.048640239 + 2 * 0.000041764768 * t _
                 - 3 * 0.000000014452093 * t ^ 2 + 6.5459673 / t
    End If
End Function

Private Function WFromPv(ByVal pv As Double, ByVal p As Double) As Double
    WFromPv = MaxD(0.621945 * pv / (p - pv), MIN_HUM_RATIO)
End Function

Private Function WFromTwbCore(ByVal tdb As Double, ByVal twb As Double, ByVal p As Double) As Double
    Dim ws As Double, w As Double
    ws = WFromPv(PwsCore(twb), p)
    If twb >= 0 Then
        w = ((2501# - 2.326 * twb) * ws - 1.006 * (tdb - twb)) / (2501# + 1.86 * tdb - 4.186 * twb)
    Else
        w = ((2830# - 0.24 * twb) * ws - 1.006 * (tdb - twb)) / (2830# + 1.86 * tdb - 2.1 * twb)
    End If
    WFromTwbCore = MaxD(w, MIN_HUM_RATIO)
End Function

Private Function TdpCore(ByVal tdb As Double, ByVal pv As Double, ByRef ok As Boolean) As Double
    Dim td As Double, tIter As Double, lnVP As Double, i As Long
    ok = False
    If pv < PwsCore(-100) Or pv > PwsCore(200) Then Exit Function
    td = tdb
    lnVP = Log(pv)
    i = 1
    Do
        tIter = td
        td = tIter - (Log(PwsCore(tIter)) - lnVP) / DLnPws(tIter)
        td = MaxD(td, -100): td = MinD(td, 200)
        If Abs(td - tIter) <= PSY_TOL Then Exit Do
        If i > MAX_ITER Then Exit Function
        i = i + 1
    Loop
    TdpCore = MinD(td, tdb)
    ok = True
End Function

Public Function FH_PSY_PWS(ByVal tC As Double) As Variant
    If tC < -100 Or tC > 200 Then FH_PSY_PWS = ErrValue(): Exit Function
    FH_PSY_PWS = PwsCore(tC)
End Function

Public Function FH_PSY_W_RH(ByVal tdbC As Double, ByVal rh As Double, ByVal pPa As Double) As Variant
    If rh < 0 Or rh > 1 Or tdbC < -100 Or tdbC > 200 Then FH_PSY_W_RH = ErrValue(): Exit Function
    FH_PSY_W_RH = WFromPv(rh * PwsCore(tdbC), pPa)
End Function

Public Function FH_PSY_W_TWB(ByVal tdbC As Double, ByVal twbC As Double, ByVal pPa As Double) As Variant
    If twbC > tdbC Then FH_PSY_W_TWB = ErrValue(): Exit Function
    FH_PSY_W_TWB = WFromTwbCore(tdbC, twbC, pPa)
End Function

Public Function FH_PSY_W_TDP(ByVal tdpC As Double, ByVal pPa As Double) As Variant
    If tdpC < -100 Or tdpC > 200 Then FH_PSY_W_TDP = ErrValue(): Exit Function
    FH_PSY_W_TDP = WFromPv(PwsCore(tdpC), pPa)
End Function

' Moist-air enthalpy in J per kg dry air
Public Function FH_PSY_H(ByVal tdbC As Double, ByVal w As Double) As Variant
    If w < 0 Then FH_PSY_H = ErrValue(): Exit Function
    FH_PSY_H = (1.006 * tdbC + MaxD(w, MIN_HUM_RATIO) * (2501# + 1.86 * tdbC)) * 1000#
End Function

Public Function FH_PSY_TDP(ByVal tdbC As Double, ByVal w As Double, ByVal pPa As Double) As Variant
    Dim ok As Boolean, pv As Double, wb As Double, r As Double
    If w < 0 Then FH_PSY_TDP = ErrValue(): Exit Function
    wb = MaxD(w, MIN_HUM_RATIO)
    pv = pPa * wb / (0.621945 + wb)
    r = TdpCore(tdbC, pv, ok)
    If Not ok Then FH_PSY_TDP = ErrValue(): Exit Function
    FH_PSY_TDP = r
End Function

Public Function FH_PSY_TWB(ByVal tdbC As Double, ByVal w As Double, ByVal pPa As Double) As Variant
    Dim ok As Boolean, wb As Double, pv As Double, tdp As Double
    Dim sup As Double, inf As Double, twb As Double, ws As Double, i As Long
    If w < 0 Then FH_PSY_TWB = ErrValue(): Exit Function
    wb = MaxD(w, MIN_HUM_RATIO)
    pv = pPa * wb / (0.621945 + wb)
    tdp = TdpCore(tdbC, pv, ok)
    If Not ok Then FH_PSY_TWB = ErrValue(): Exit Function
    sup = tdbC: inf = tdp
    twb = (inf + sup) / 2
    i = 1
    Do While (sup - inf) > PSY_TOL
        ws = WFromTwbCore(tdbC, twb, pPa)
        If ws > wb Then sup = twb Else inf = twb
        twb = (sup + inf) / 2
        If i >= MAX_ITER Then FH_PSY_TWB = ErrValue(): Exit Function
        i = i + 1
    Loop
    FH_PSY_TWB = twb
End Function

'------------------------------------------------------------------ macro
' Builds a "Calculator" sheet: labelled inputs (blue) and live formulas using the UDFs.
Private Sub Hdr(ByVal ws As Worksheet, ByRef r As Long, ByVal label As String)
    r = r + 1
    ws.Cells(r, 1).Value = label
    ws.Cells(r, 1).Font.Bold = True
    r = r + 1
End Sub

Private Function Inp(ByVal ws As Worksheet, ByRef r As Long, ByVal label As String, ByVal v As Double, ByVal unit As String) As String
    ws.Cells(r, 1).Value = label
    ws.Cells(r, 2).Value = v
    ws.Cells(r, 2).Font.Color = RGB(0, 0, 192)
    ws.Cells(r, 3).Value = unit
    Inp = "B" & r
    r = r + 1
End Function

Private Function Calc(ByVal ws As Worksheet, ByRef r As Long, ByVal label As String, ByVal f As String, ByVal unit As String) As String
    ws.Cells(r, 1).Value = label
    ws.Cells(r, 2).Formula = f
    ws.Cells(r, 3).Value = unit
    Calc = "B" & r
    r = r + 1
End Function

Public Sub FillCalcSheet()
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets("Calculator")
    On Error GoTo 0
    If ws Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add(Before:=ThisWorkbook.Worksheets(1))
        ws.Name = "Calculator"
    End If
    ws.Cells.Clear

    Dim r As Long
    r = 1
    ws.Cells(r, 1).Value = "Fab HVAC calculator - inputs in blue are illustrative; replace with project data"
    ws.Cells(r, 1).Font.Bold = True
    r = 2

    Dim cN As String, cD As String, cA As String, cH As String, cCov As String, cV As String, cFfu As String
    Dim cQ As String, cDb As String, cWb As String, cP As String, cW As String
    Dim cLoad As String, cChl As String, cChwp As String, cCdwp As String, cCt As String, cChws As String
    Dim cCap As String, cEff As String, cTin As String, cTout As String, cTwb As String, tmp As String

    Hdr ws, r, "Cleanliness (ISO 14644-1)"
    cN = Inp(ws, r, "ISO class N", 5, "-")
    cD = Inp(ws, r, "Particle size D", 0.5, "um")
    tmp = Calc(ws, r, "Class limit Cn = 10^N (0.1/D)^2.08", "=FH_ISO_CLASS_LIMIT(" & cN & "," & cD & ")", "particles/m3")

    Hdr ws, r, "Unidirectional airflow"
    cA = Inp(ws, r, "Floor area", 600, "m2")
    cH = Inp(ws, r, "Clear height", 4, "m")
    cCov = Inp(ws, r, "Ceiling FFU coverage", 1, "fraction")
    cV = Inp(ws, r, "Face velocity", 0.4, "m/s")
    cFfu = Inp(ws, r, "FFU face area", 0.72, "m2")
    cQ = Calc(ws, r, "Supply airflow", "=FH_UD_AIRFLOW(" & cV & "," & cA & "*" & cCov & ")", "m3/s")
    tmp = Calc(ws, r, "FFU count", "=FH_FFU_COUNT(" & cA & "," & cCov & "," & cFfu & ")", "-")
    tmp = Calc(ws, r, "Air changes", "=FH_ACH(" & cQ & "," & cA & "*" & cH & ")", "1/h")

    Hdr ws, r, "Outdoor air - Singapore Changi, ASHRAE 2021 0.4% cooling DB / MCWB"
    cDb = Inp(ws, r, "Dry bulb", 33.2, "degC")
    cWb = Inp(ws, r, "Mean coincident wet bulb", 26.3, "degC")
    cP = Inp(ws, r, "Pressure", 101240, "Pa")
    cW = Calc(ws, r, "Humidity ratio", "=FH_PSY_W_TWB(" & cDb & "," & cWb & "," & cP & ")", "kg/kg")
    tmp = Calc(ws, r, "Enthalpy", "=FH_PSY_H(" & cDb & "," & cW & ")/1000", "kJ/kg")
    tmp = Calc(ws, r, "Dew point", "=FH_PSY_TDP(" & cDb & "," & cW & "," & cP & ")", "degC")

    Hdr ws, r, "Chiller plant vs NEA MEES"
    cLoad = Inp(ws, r, "Cooling delivered", 4000, "kW")
    cChl = Inp(ws, r, "Chillers", 560, "kW")
    cChwp = Inp(ws, r, "Chilled-water pumps", 70, "kW")
    cCdwp = Inp(ws, r, "Condenser-water pumps", 80, "kW")
    cCt = Inp(ws, r, "Cooling towers", 45, "kW")
    cChws = Inp(ws, r, "CHW supply temperature", 6.5, "degC")
    cCap = Inp(ws, r, "Installed capacity", 7000, "kW")
    cEff = Calc(ws, r, "System efficiency", "=FH_PLANT_EFF(" & cLoad & "," & cChl & "," & cChwp & "," & cCdwp & "," & cCt & ")", "kWe/kWc")
    tmp = Calc(ws, r, "System efficiency", "=FH_KWEKWC_TO_KWRT(" & cEff & ")", "kW/RT")
    tmp = Calc(ws, r, "NEA MEES limit", "=FH_MEES_LIMIT(" & cChws & ")", "kWe/kWc")
    tmp = Calc(ws, r, "NEA MEES verdict", "=FH_MEES_CHECK(" & cEff & "," & cChws & "," & cCap & ")", "")

    Hdr ws, r, "Cooling tower"
    cTin = Inp(ws, r, "Water in", 37, "degC")
    cTout = Inp(ws, r, "Water out", 31.5, "degC")
    cTwb = Inp(ws, r, "Entering wet bulb", 27.5, "degC")
    tmp = Calc(ws, r, "Range", "=FH_CT_RANGE(" & cTin & "," & cTout & ")", "K")
    tmp = Calc(ws, r, "Approach", "=FH_CT_APPROACH(" & cTout & "," & cTwb & ")", "K")
    tmp = Calc(ws, r, "Effectiveness", "=FH_CT_EFFECTIVENESS(" & cTin & "," & cTout & "," & cTwb & ")", "-")

    ws.Columns("A:C").AutoFit
End Sub
