      ******************************************************************
      * INTCALC.CBL
      * Deposit interest calculation module - THE ORACLE.
      * This is the golden, ground-truth business logic. It is executed
      * (never read as a listing) via the shipped GnuCOBOL runtime by
      * core/cobol_runner.py. Nothing in ai/ may derive expectations
      * from anything other than running this program.
      *
      * Protocol: one pipe-delimited line on STDIN, one pipe-delimited
      * line on STDOUT. See data/signature/io_signature.yaml for the
      * authoritative field contract.
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INTCALC.

       ENVIRONMENT DIVISION.

       DATA DIVISION.
       WORKING-STORAGE SECTION.

       01  WS-INPUT-LINE            PIC X(80).

      * ---- Parsed input fields (zoned / display, as received) -------
       01  WS-IN-ACCTID             PIC X(6).
       01  WS-IN-BALANCE-X          PIC X(11).
       01  WS-IN-ADJRAW             PIC X(8).
       01  WS-IN-YY                 PIC X(2).
       01  WS-IN-MM                 PIC X(2).
       01  WS-IN-DD                 PIC X(2).

      * ---- Working copybook record (packed-decimal fields) ----------
       COPY ACCTREC.

      * ---- Overpunch decode table (zoned trailing-sign convention) --
      *      positive: 0=EMPTY... uses letters: {ABCDEFGHI = 0..9 (+)
      *      negative: }JKLMNOPQR = 0..9 (-)
       01  WS-OP-POS-TABLE          PIC X(10) VALUE "{ABCDEFGHI".
       01  WS-OP-NEG-TABLE          PIC X(10) VALUE "}JKLMNOPQR".
       01  WS-OP-LAST-CHAR          PIC X(1).
       01  WS-OP-IDX                PIC 9(2).
       01  WS-OP-SIGN               PIC X(1).
       01  WS-OP-DIGIT              PIC 9(1).
       01  WS-ADJ-DIGITS            PIC 9(7).
       01  WS-ADJ-SIGNED            PIC S9(5)V99 COMP-3.

      * ---- Year pivot ------------------------------------------------
       01  WS-YY-NUM                PIC 9(2).
       01  WS-EFFECTIVE-YEAR        PIC 9(4).

      * ---- Interest computation --------------------------------------
       01  WS-TIER                  PIC 9(1).
       01  WS-RATE                  PIC V999      COMP-3.
       01  WS-RAW-INTEREST          PIC S9(7)V999 COMP-3.
       01  WS-INTEREST              PIC S9(7)V99  COMP-3.
       01  WS-CAP-LIMIT             PIC S9(7)V99  COMP-3 VALUE 500.00.
       01  WS-CAPPED-FLAG           PIC X(1)      VALUE "N".

      * ---- Output ------------------------------------------------
       01  WS-OUT-LINE              PIC X(80).
       01  WS-OUT-INTEREST-X        PIC -(6)9.99.
       01  WS-OUT-ADJ-X             PIC 9(5).99.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           ACCEPT WS-INPUT-LINE FROM CONSOLE.
           PERFORM PARSE-INPUT.
           PERFORM DECODE-OVERPUNCH.
           PERFORM RESOLVE-YEAR.
           PERFORM COMPUTE-INTEREST.
           PERFORM APPLY-UNDOCUMENTED-CAP.
           PERFORM BUILD-OUTPUT.
           DISPLAY WS-OUT-LINE.
           STOP RUN.

       PARSE-INPUT.
      * Fixed-width pipe protocol: ACCTID|BALANCE|ADJRAW|YY|MM|DD
           UNSTRING WS-INPUT-LINE DELIMITED BY "|"
               INTO WS-IN-ACCTID
                    WS-IN-BALANCE-X
                    WS-IN-ADJRAW
                    WS-IN-YY
                    WS-IN-MM
                    WS-IN-DD
           END-UNSTRING.
           MOVE WS-IN-ACCTID       TO ACR-ACCOUNT-ID.
           COMPUTE ACR-BALANCE = FUNCTION NUMVAL(WS-IN-BALANCE-X).

      * ------------------------------------------------------------
      * R-009 / R-010: packed-decimal interest arithmetic uses this
      * module's own COMP-3 field and its ROUNDED clause (round-half-
      * away-from-zero at the half cent). This is the ground truth
      * a reimplementation is measured against; do not read this as
      * "the rounding rule" text - the rule text is in
      * validated_rules.yaml and is deliberately silent on the
      * half-cent tie-break, which is exactly the divergence the
      * exercise wants surfaced, not hidden.
      * ------------------------------------------------------------

       DECODE-OVERPUNCH.
      * R-011: last character of the adjustment field carries the
      * sign via zoned trailing overpunch; digits 1-7 are the
      * unsigned magnitude in cents-of-thousands (9(5)V99).
           MOVE WS-IN-ADJRAW(8:1) TO WS-OP-LAST-CHAR.
           PERFORM VARYING WS-OP-IDX FROM 1 BY 1
                   UNTIL WS-OP-IDX > 10
               IF WS-OP-POS-TABLE(WS-OP-IDX:1) = WS-OP-LAST-CHAR
                   MOVE "+" TO WS-OP-SIGN
                   COMPUTE WS-OP-DIGIT = WS-OP-IDX - 1
                   MOVE WS-IN-ADJRAW(1:7) TO WS-ADJ-DIGITS
                   MOVE WS-OP-DIGIT TO WS-ADJ-DIGITS(7:1)
                   COMPUTE WS-ADJ-SIGNED = WS-ADJ-DIGITS / 100
               END-IF
               IF WS-OP-NEG-TABLE(WS-OP-IDX:1) = WS-OP-LAST-CHAR
                   MOVE "-" TO WS-OP-SIGN
                   COMPUTE WS-OP-DIGIT = WS-OP-IDX - 1
                   MOVE WS-IN-ADJRAW(1:7) TO WS-ADJ-DIGITS
                   MOVE WS-OP-DIGIT TO WS-ADJ-DIGITS(7:1)
                   COMPUTE WS-ADJ-SIGNED = (WS-ADJ-DIGITS / 100) * -1
               END-IF
           END-PERFORM.
      * R-012: a decoded magnitude of zero is always reported positive.
           IF WS-ADJ-SIGNED = 0
               MOVE "+" TO WS-OP-SIGN
           END-IF.

       RESOLVE-YEAR.
      * R-013: two-digit year window, pivot at 50. YY >= 50 => 19YY,
      * YY < 50 => 20YY.
           MOVE WS-IN-YY TO WS-YY-NUM.
           IF WS-YY-NUM >= 50
               COMPUTE WS-EFFECTIVE-YEAR = 1900 + WS-YY-NUM
           ELSE
               COMPUTE WS-EFFECTIVE-YEAR = 2000 + WS-YY-NUM
           END-IF.

       COMPUTE-INTEREST.
      * R-014: three-tier interest, tier chosen by balance.
      *   Tier 1: balance strictly greater than 0    and up to  1000.00
      *   Tier 2: balance strictly greater than 1000.00 up to  10000.00
      *   Tier 3: balance strictly greater than 10000.00
      * NOTE (deliberate ambiguity, R-014): the COBOL below tests the
      * lower tier boundaries with GREATER THAN, i.e. a balance of
      * EXACTLY 1000.00 falls in tier 1, not tier 2. Every plain-English
      * reading of "up to 1000" is ambiguous between > and >=; that
      * ambiguity is the point, not a bug to silently resolve.
           IF ACR-BALANCE > 10000.00
               MOVE 3 TO WS-TIER
               MOVE 0.030 TO WS-RATE
           ELSE
               IF ACR-BALANCE > 1000.00
                   MOVE 2 TO WS-TIER
                   MOVE 0.020 TO WS-RATE
               ELSE
                   MOVE 1 TO WS-TIER
                   MOVE 0.010 TO WS-RATE
               END-IF
           END-IF.
           COMPUTE WS-RAW-INTEREST = ACR-BALANCE * WS-RATE.
           COMPUTE WS-INTEREST ROUNDED = WS-RAW-INTEREST.

       APPLY-UNDOCUMENTED-CAP.
      * NOT DESCRIBED BY ANY RULE IN data/rules/validated_rules.yaml.
      * This branch exists in the shipped module and nowhere else.
      * It is the seeded "untraceable behaviour" pathology: the
      * traceability checker (core/traceability.py) must surface it
      * as an unexplained code path, and ai/implementation.py must
      * NOT silently reproduce it as if it were a real rule - it
      * should be reported in the evidence pack instead.
           IF WS-TIER = 3 AND WS-INTEREST > WS-CAP-LIMIT
               MOVE WS-CAP-LIMIT TO WS-INTEREST
               MOVE "Y" TO WS-CAPPED-FLAG
           END-IF.

       BUILD-OUTPUT.
           MOVE WS-INTEREST   TO WS-OUT-INTEREST-X.
           MOVE WS-ADJ-SIGNED TO WS-OUT-ADJ-X.
           STRING WS-TIER              DELIMITED BY SIZE
                  "|"                  DELIMITED BY SIZE
                  WS-OUT-INTEREST-X    DELIMITED BY SIZE
                  "|"                  DELIMITED BY SIZE
                  WS-OP-SIGN           DELIMITED BY SIZE
                  WS-OUT-ADJ-X         DELIMITED BY SIZE
                  "|"                  DELIMITED BY SIZE
                  WS-EFFECTIVE-YEAR    DELIMITED BY SIZE
                  "|"                  DELIMITED BY SIZE
                  WS-CAPPED-FLAG       DELIMITED BY SIZE
               INTO WS-OUT-LINE.
