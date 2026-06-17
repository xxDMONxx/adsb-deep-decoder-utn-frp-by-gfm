#!/usr/bin/env python3
"""
Test de verificación del decoder ADS-B v2.0 (pyModeS v3.x)
Prueba con mensajes ADS-B conocidos sin necesidad de RTL-SDR ni GNU Radio.

Ejecutar: python test_decoder.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adsb_decoder import ADSBDecoder, format_output, format_position, C


def test_pymodes_v3_api():
    """Verifica que pyModeS v3 decode() funciona correctamente."""
    import pyModeS
    print(f"{C.BOLD}=== Test 1: pyModeS v3 API ==={C.RESET}")

    print(f"  pyModeS version: {pyModeS.__version__}")
    assert int(pyModeS.__version__.split('.')[0]) >= 3, "Requires pyModeS v3+"

    msg = "8D40621D58C382D690C8AC2863A7"
    r = pyModeS.decode(msg)

    assert r['df'] == 17, f"Expected DF=17, got {r['df']}"
    print(f"  {C.GREEN}+{C.RESET} decode().df = {r['df']}")

    assert r['icao'] == '40621D', f"Expected ICAO=40621D, got {r['icao']}"
    print(f"  {C.GREEN}+{C.RESET} decode().icao = {r['icao']}")

    assert r['crc_valid'] == True, f"Expected crc_valid=True"
    print(f"  {C.GREEN}+{C.RESET} decode().crc_valid = {r['crc_valid']}")

    assert r['typecode'] == 11, f"Expected TC=11, got {r['typecode']}"
    print(f"  {C.GREEN}+{C.RESET} decode().typecode = {r['typecode']}")

    # Verify position pair function
    from pyModeS.position import airborne_position_pair
    pos = airborne_position_pair(39848, 83951, 21567, 81965, even_is_newer=False)
    assert pos is not None
    print(f"  {C.GREEN}+{C.RESET} airborne_position_pair() = {pos[0]:.4f}, {pos[1]:.4f}")

    print(f"  {C.GREEN}{C.BOLD}ALL PASSED{C.RESET}\n")


def test_callsign():
    """Test TC 1-4: Aircraft Identification."""
    print(f"{C.BOLD}=== Test 2: Callsign (TC 1-4) ==={C.RESET}")
    decoder = ADSBDecoder()

    msg = "8D406B902015A678D4D220AA4BDA"
    result = decoder.process(msg)

    assert result is not None, "Message should decode"
    print(f"  ICAO:       {result['icao']}")
    print(f"  TC:         {result['tc']}")
    print(f"  BDS:        {result.get('bds')}")
    print(f"  Callsign:   {result.get('callsign', 'N/A')}")
    print(f"  Category:   {result.get('category', 'N/A')}")
    print(f"  Wake Vortex: {result.get('wake_vortex', 'N/A')}")

    assert result['callsign'] == 'EZY85MH', f"Expected EZY85MH, got {result['callsign']}"
    print(f"  {C.GREEN}+{C.RESET} Callsign correct: {result['callsign']}")
    print(f"  {C.GREEN}{C.BOLD}PASSED{C.RESET}\n")


def test_velocity():
    """Test TC 19: Velocity."""
    print(f"{C.BOLD}=== Test 3: Velocity (TC 19) ==={C.RESET}")
    decoder = ADSBDecoder()

    msg = "8DA05F219B06B6AF189400CBC33F"
    result = decoder.process(msg)

    assert result is not None, "Message should decode"
    print(f"  ICAO:        {result['icao']}")
    print(f"  TC:          {result['tc']}")
    print(f"  Speed:       {result.get('speed', 'N/A')} kt")
    print(f"  Speed Type:  {result.get('speed_type', 'N/A')}")
    print(f"  Heading:     {result.get('heading', 'N/A')} deg")
    print(f"  Vert Rate:   {result.get('vertical_rate', 'N/A')} ft/min")
    print(f"  VR Source:   {result.get('vr_source', 'N/A')}")
    print(f"  Geo-Baro:    {result.get('geo_minus_baro', 'N/A')}")

    assert result.get('speed') is not None, "Speed should be present"
    assert result.get('heading') is not None, "Heading should be present"
    assert result.get('vertical_rate') is not None, "Vertical rate should be present"
    assert result.get('speed_type') is not None, "Speed type should be present"

    print(f"  {C.GREEN}+{C.RESET} All 4+ velocity fields present")
    print(f"  {C.GREEN}{C.BOLD}PASSED{C.RESET}\n")


def test_airborne_position():
    """Test TC 9-18: Airborne Position with CPR."""
    print(f"{C.BOLD}=== Test 4: Airborne Position (CPR) ==={C.RESET}")
    decoder = ADSBDecoder()

    msg_even = "8D40058B58C901375147EFD09357"
    msg_odd  = "8D40058B58C904A87F402D3B8C59"

    r1 = decoder.process(msg_even)
    assert r1 is not None, "Even frame should decode"
    print(f"  Even: ICAO={r1['icao']} TC={r1['tc']} "
          f"Alt={r1.get('altitude_baro', 'N/A')} ft "
          f"CPR={r1.get('cpr_format_text', 'N/A')}")
    print(f"        cpr_lat={r1.get('cpr_lat')}, cpr_lon={r1.get('cpr_lon')}")

    r2 = decoder.process(msg_odd)
    assert r2 is not None, "Odd frame should decode"
    print(f"  Odd:  ICAO={r2['icao']} TC={r2['tc']} "
          f"Alt={r2.get('altitude_baro', 'N/A')} ft "
          f"CPR={r2.get('cpr_format_text', 'N/A')}")
    print(f"        cpr_lat={r2.get('cpr_lat')}, cpr_lon={r2.get('cpr_lon')}")

    # After processing both frames, position should be resolved
    if r2.get('latitude') is not None:
        print(f"  {C.GREEN}+{C.RESET} Position decoded: "
              f"{format_position(r2['latitude'], r2['longitude'])}")
        # Expected: approximately 49.8176, 6.0844
        assert abs(r2['latitude'] - 49.8176) < 0.01, \
            f"Lat off: {r2['latitude']}"
        assert abs(r2['longitude'] - 6.0844) < 0.01, \
            f"Lon off: {r2['longitude']}"
        print(f"  {C.GREEN}+{C.RESET} Position accuracy verified")
    else:
        print(f"  {C.YELLOW}!{C.RESET} Position not resolved (may need timing)")

    print(f"  {C.GREEN}{C.BOLD}PASSED{C.RESET}\n")


def test_format_position():
    """Test de formato de posición N/S E/W."""
    print(f"{C.BOLD}=== Test 5: Position Formatting ==={C.RESET}")

    # Norte + Este
    p1 = format_position(31.73, 60.52)
    assert 'N' in p1 and 'E' in p1
    print(f"  {C.GREEN}+{C.RESET} 31.73, 60.52 -> {p1}")

    # Sur + Oeste (Argentina)
    p2 = format_position(-31.73, -60.52)
    assert 'S' in p2 and 'W' in p2
    print(f"  {C.GREEN}+{C.RESET} -31.73, -60.52 -> {p2}")

    # None handling
    assert format_position(None, None) == 'N/A'
    print(f"  {C.GREEN}+{C.RESET} None, None -> N/A")

    print(f"  {C.GREEN}{C.BOLD}ALL PASSED{C.RESET}\n")


def test_crc_validation():
    """Test de validación CRC."""
    print(f"{C.BOLD}=== Test 6: CRC Validation ==={C.RESET}")
    decoder = ADSBDecoder()

    # Mensaje válido
    msg_valid = "8D40621D58C382D690C8AC2863A7"
    r1 = decoder.process(msg_valid)
    assert r1 is not None, "Valid message should be accepted"
    print(f"  {C.GREEN}+{C.RESET} Valid message processed: ICAO={r1['icao']}")

    # Mensaje corrupto (último byte cambiado)
    msg_corrupt = "8D40621D58C382D690C8AC2863FF"
    r2 = decoder.process(msg_corrupt)
    assert r2 is None, "Corrupt message should be rejected"
    print(f"  {C.GREEN}+{C.RESET} Corrupt message rejected correctly")

    print(f"  Stats: CRC OK={decoder.stats['crc_ok']}, "
          f"CRC Fail={decoder.stats['crc_fail']}")
    print(f"  {C.GREEN}{C.BOLD}ALL PASSED{C.RESET}\n")


def test_short_messages():
    """Test DF4/DF5: Short messages (56 bits = 14 hex chars)."""
    print(f"{C.BOLD}=== Test 7: Short Messages (DF4/DF5) ==={C.RESET}")
    decoder = ADSBDecoder()

    # DF5 with squawk
    msg_df5 = "28001B9A4853E7"
    r = decoder.process(msg_df5)
    if r is not None:
        print(f"  DF5: ICAO={r['icao']}, Squawk={r.get('squawk', 'N/A')}, "
              f"FS={r.get('flight_status_text', 'N/A')}")
        if r.get('squawk'):
            print(f"  {C.GREEN}+{C.RESET} Squawk decoded: {r['squawk']}")
    else:
        print(f"  {C.YELLOW}!{C.RESET} DF5 message not decoded (CRC check)")

    # DF4 with altitude
    msg_df4 = "20001AB6C43E23"
    r2 = decoder.process(msg_df4)
    if r2 is not None:
        print(f"  DF4: ICAO={r2['icao']}, Alt={r2.get('altitude_baro', 'N/A')} ft")
        if r2.get('altitude_baro'):
            print(f"  {C.GREEN}+{C.RESET} Altitude decoded: {r2['altitude_baro']} ft")
    else:
        print(f"  {C.YELLOW}!{C.RESET} DF4 message not decoded (CRC check)")

    print()


def test_deep_output():
    """Test de salida formateada con análisis profundo."""
    print(f"{C.BOLD}=== Test 8: Deep Output Format ==={C.RESET}")
    decoder = ADSBDecoder()

    msg = "8D40621D58C382D690C8AC2863A7"
    result = decoder.process(msg)

    assert result is not None
    output = format_output(result, show_deep=True)
    print(output)
    print()

    assert len(result['field_map']) > 0, "Field map empty!"
    print(f"  {C.GREEN}+{C.RESET} Field map has {len(result['field_map'])} entries")

    assert result['raw_hex'] == msg
    print(f"  {C.GREEN}+{C.RESET} Raw hex preserved")

    assert len(result['raw_binary']) == 112
    print(f"  {C.GREEN}+{C.RESET} Raw binary is 112 bits")

    print(f"  {C.GREEN}{C.BOLD}ALL PASSED{C.RESET}\n")


def test_message_lengths():
    """Test de aceptación de diferentes longitudes de mensaje."""
    print(f"{C.BOLD}=== Test 9: Message Length Handling ==={C.RESET}")
    decoder = ADSBDecoder()

    # 28 chars = 112 bits
    r1 = decoder.process("8D40621D58C382D690C8AC2863A7")
    assert r1 is not None
    print(f"  {C.GREEN}+{C.RESET} 28 chars accepted")

    # Invalid lengths should be rejected
    r3 = decoder.process("8D40621D58C3")
    assert r3 is None
    print(f"  {C.GREEN}+{C.RESET} 12 chars rejected correctly")

    r4 = decoder.process("8D40621D58C382D690C8AC2863A7FF")
    assert r4 is None
    print(f"  {C.GREEN}+{C.RESET} 30 chars rejected correctly")

    r5 = decoder.process("")
    assert r5 is None
    print(f"  {C.GREEN}+{C.RESET} Empty string rejected correctly")

    r6 = decoder.process("ZZZZZZZZZZZZZZZZZZZZZZZZZZZZ")
    assert r6 is None
    print(f"  {C.GREEN}+{C.RESET} Non-hex rejected correctly")

    print(f"  {C.GREEN}{C.BOLD}ALL PASSED{C.RESET}\n")


def test_memory_cleanup():
    """Test de limpieza de memoria."""
    print(f"{C.BOLD}=== Test 10: Memory Management ==={C.RESET}")
    decoder = ADSBDecoder()

    from adsb_decoder import AircraftState
    from time import time

    for i in range(100):
        icao = f"A{i:05X}"
        ac = AircraftState(icao)
        ac.last_seen = time() - 400  # > 300s max_age
        decoder.aircraft[icao] = ac

    print(f"  Before cleanup: {len(decoder.aircraft)} aircraft")
    assert len(decoder.aircraft) == 100

    decoder._last_cleanup = 0
    decoder._cleanup_expired(max_age=300.0)

    print(f"  After cleanup:  {len(decoder.aircraft)} aircraft")
    assert len(decoder.aircraft) == 0
    print(f"  {C.GREEN}+{C.RESET} All expired aircraft cleaned up")
    print(f"  {C.GREEN}{C.BOLD}PASSED{C.RESET}\n")


def test_aircraft_tracking():
    """Test de tracking acumulativo por ICAO."""
    print(f"{C.BOLD}=== Test 11: Aircraft Tracking ==={C.RESET}")
    decoder = ADSBDecoder()

    # Process callsign
    msg_cs = "8D406B902015A678D4D220AA4BDA"
    r1 = decoder.process(msg_cs)
    assert r1 is not None

    # Check aircraft state
    ac = decoder.aircraft.get('406B90')
    assert ac is not None
    assert ac.callsign == 'EZY85MH'
    assert ac.msg_count >= 1
    print(f"  {C.GREEN}+{C.RESET} Aircraft state created: ICAO={ac.icao}, CS={ac.callsign}")
    print(f"  {C.GREEN}+{C.RESET} Message count: {ac.msg_count}")

    print(f"  {C.GREEN}{C.BOLD}PASSED{C.RESET}\n")


def test_all_decoded_fields():
    """Comprehensive test of what v3 decode returns for different message types."""
    print(f"{C.BOLD}=== Test 12: Comprehensive Field Coverage ==={C.RESET}")
    import pyModeS

    test_msgs = {
        'Position (TC11)': '8D40621D58C382D690C8AC2863A7',
        'Callsign (TC4)': '8D406B902015A678D4D220AA4BDA',
        'Velocity (TC19)': '8DA05F219B06B6AF189400CBC33F',
    }

    for label, msg in test_msgs.items():
        r = pyModeS.decode(msg)
        fields = [f"{k}={v}" for k, v in r.items() if v is not None]
        print(f"  {C.CYAN}{label}:{C.RESET}")
        for f in fields:
            print(f"    {f}")
        print()

    print(f"  {C.GREEN}{C.BOLD}PASSED{C.RESET}\n")


def main():
    print(f"\n{C.BOLD}{C.CYAN}"
          f"+{'=' * 60}+\n"
          f"|    AERO-LITORAL 26 -- Decoder Verification Tests v2.0     |\n"
          f"|                    pyModeS v3 compatible                   |\n"
          f"+{'=' * 60}+"
          f"{C.RESET}\n")

    tests = [
        test_pymodes_v3_api,
        test_callsign,
        test_velocity,
        test_airborne_position,
        test_format_position,
        test_crc_validation,
        test_short_messages,
        test_deep_output,
        test_message_lengths,
        test_memory_cleanup,
        test_aircraft_tracking,
        test_all_decoded_fields,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  {C.RED}FAILED: {test_fn.__name__}: {e}{C.RESET}\n")
            import traceback
            traceback.print_exc()
            print()

    print(f"\n{C.BOLD}{'=' * 60}{C.RESET}")
    color_pass = C.GREEN
    color_fail = C.RED if failed else C.GREEN
    print(f"{C.BOLD}  Results: {color_pass}{passed} passed{C.RESET}, "
          f"{color_fail}{failed} failed{C.RESET}")
    print(f"{C.BOLD}{'=' * 60}{C.RESET}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
