      ******************************************************************
      * WIREPAY.CBL
      * Domestic outbound wire payment processing module - THE ORACLE.
      * This is the golden, ground-truth business logic for domestic
      * wire payments: validates the beneficiary routing number and the
      * amount, computes the wire fee (a flat base fee by amount tier,
      * plus an optional priority surcharge and a compliance-monitoring
      * surcharge), the total amount debited from the originating
      * account, and whether the payment settles same-day or next
      * business day based on the submission cutoff time.
      *
      * Protocol: one pipe-delimited line on STDIN, one pipe-delimited
      * line on STDOUT - same convention as INTCALC.cbl. See
      * data/signature/wirepay_io_signature.yaml for the authoritative
      * field contract.
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WIREPAY.

       ENVIRONMENT DIVISION.

       DATA DIVISION.
       WORKING-STORAGE SECTION.

       01  WS-INPUT-LINE            PIC X(80).

      * ---- Parsed input fields (as received) -------------------------
       01  WS-IN-PAYMENT-ID         PIC X(10).
       01  WS-IN-ORIG-ACCT          PIC X(10).
       01  WS-IN-BENE-ACCT          PIC X(10).
       01  WS-IN-BENE-ROUTING       PIC X(9).
       01  WS-IN-AMOUNT-X           PIC X(11).
       01  WS-IN-SUBMIT-HH          PIC X(2).
       01  WS-IN-SUBMIT-MM          PIC X(2).
       01  WS-IN-PRIORITY-FLAG      PIC X(1).

      * ---- Working numeric fields --------------------------------
       01  WS-AMOUNT                PIC S9(9)V99   COMP-3.
       01  WS-SUBMIT-HH-NUM         PIC 9(2).
       01  WS-SUBMIT-MM-NUM         PIC 9(2).
       01  WS-SUBMIT-HHMM           PIC 9(4).
       01  WS-CUTOFF-HHMM           PIC 9(4)       VALUE 1500.

      * ---- Validation ----------------------------------------------
       01  WS-STATUS                PIC X(8)       VALUE "ACCEPTED".
       01  WS-REJECT-REASON         PIC X(16)      VALUE SPACES.

      * ---- Fee computation --------------------------------------
       01  WS-BASE-FEE              PIC S9(5)V99   COMP-3   VALUE 0.
       01  WS-PRIORITY-FEE          PIC S9(5)V99   COMP-3   VALUE 0.
       01  WS-COMPLIANCE-RAW        PIC S9(9)V999  COMP-3   VALUE 0.
       01  WS-COMPLIANCE-FEE        PIC S9(5)V99   COMP-3   VALUE 0.
       01  WS-REVIEW-FEE            PIC S9(5)V99   COMP-3   VALUE 0.
       01  WS-TOTAL-FEE             PIC S9(5)V99   COMP-3   VALUE 0.
       01  WS-TOTAL-DEBIT           PIC S9(9)V99   COMP-3   VALUE 0.
       01  WS-VALUE-DATE-OFFSET     PIC 9(1)                VALUE 0.

      * ---- Output ------------------------------------------------
       01  WS-OUT-LINE              PIC X(80).
       01  WS-OUT-FEE-X             PIC -(4)9.99.
       01  WS-OUT-DEBIT-X           PIC -(8)9.99.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           ACCEPT WS-INPUT-LINE FROM CONSOLE.
           PERFORM PARSE-INPUT.
           PERFORM VALIDATE-INPUT.
           IF WS-STATUS = "ACCEPTED"
               PERFORM COMPUTE-FEES
               PERFORM APPLY-UNDOCUMENTED-REVIEW-FEE
               PERFORM COMPUTE-TOTAL-DEBIT
               PERFORM RESOLVE-VALUE-DATE
           END-IF.
           PERFORM BUILD-OUTPUT.
           DISPLAY WS-OUT-LINE.
           STOP RUN.

       PARSE-INPUT.
      * Fixed-width pipe protocol:
      * PAYMENT_ID|ORIG_ACCT|BENE_ACCT|BENE_ROUTING|AMOUNT|HH|MM|PRIORITY
           UNSTRING WS-INPUT-LINE DELIMITED BY "|"
               INTO WS-IN-PAYMENT-ID
                    WS-IN-ORIG-ACCT
                    WS-IN-BENE-ACCT
                    WS-IN-BENE-ROUTING
                    WS-IN-AMOUNT-X
                    WS-IN-SUBMIT-HH
                    WS-IN-SUBMIT-MM
                    WS-IN-PRIORITY-FLAG
           END-UNSTRING.
           COMPUTE WS-AMOUNT = FUNCTION NUMVAL(WS-IN-AMOUNT-X).
           MOVE WS-IN-SUBMIT-HH TO WS-SUBMIT-HH-NUM.
           MOVE WS-IN-SUBMIT-MM TO WS-SUBMIT-MM-NUM.

       VALIDATE-INPUT.
      * R-WP-001: the beneficiary routing number must be exactly 9
      * numeric digits (its field width is fixed at 9; this rejects any
      * non-digit content - blanks, letters, a short/garbled value).
           IF WS-IN-BENE-ROUTING NOT NUMERIC
               MOVE "REJECTED" TO WS-STATUS
               MOVE "INVALID_ROUTING" TO WS-REJECT-REASON
           ELSE
      * R-WP-002: amount must be strictly greater than zero.
               IF WS-AMOUNT NOT > 0
                   MOVE "REJECTED" TO WS-STATUS
                   MOVE "INVALID_AMOUNT" TO WS-REJECT-REASON
               END-IF
           END-IF.

       COMPUTE-FEES.
      * R-WP-003: flat base fee by amount tier.
      * NOTE (deliberate ambiguity, same pattern as INTCALC's R-014):
      * the boundary below is tested with GREATER THAN, so a wire of
      * EXACTLY $10,000.00 falls in the LOWER-fee bracket ($25), not
      * the large-wire bracket ($15). Every plain-English reading of
      * "up to $10,000" is ambiguous between > and >=; the ambiguity is
      * the point, not a bug to silently resolve.
           IF WS-AMOUNT > 10000.00
               MOVE 15.00 TO WS-BASE-FEE
           ELSE
               MOVE 25.00 TO WS-BASE-FEE
           END-IF.

      * R-WP-004: priority (expedited) wires add a flat $10 surcharge.
           IF WS-IN-PRIORITY-FLAG = "Y"
               MOVE 10.00 TO WS-PRIORITY-FEE
           ELSE
               MOVE 0.00 TO WS-PRIORITY-FEE
           END-IF.

      * R-WP-005: a compliance-monitoring surcharge of 0.01% of the
      * amount is added, rounded to the nearest cent. This module's own
      * COMP-3 ROUNDED clause resolves an exact half-cent tie AWAY FROM
      * ZERO; the rule text is deliberately silent on the tie-break
      * convention - same pattern as INTCALC's R-009/R-010.
           COMPUTE WS-COMPLIANCE-RAW = WS-AMOUNT * 0.0001.
           COMPUTE WS-COMPLIANCE-FEE ROUNDED = WS-COMPLIANCE-RAW.

      * R-WP-006: total fee is the sum of the three components above.
           COMPUTE WS-TOTAL-FEE = WS-BASE-FEE + WS-PRIORITY-FEE
                                   + WS-COMPLIANCE-FEE.

       APPLY-UNDOCUMENTED-REVIEW-FEE.
      * NOT DESCRIBED BY ANY RULE IN data/rules/wirepay_rules.yaml.
      * This branch exists in the shipped module and nowhere else - the
      * seeded "untraceable behaviour" pathology, exactly like
      * INTCALC's undocumented interest cap. core/traceability.py must
      * surface this as an unexplained code path, and any reimplementation
      * must NOT silently guess at it rather than reporting it.
           IF WS-AMOUNT > 250000.00
               MOVE 50.00 TO WS-REVIEW-FEE
               COMPUTE WS-TOTAL-FEE = WS-TOTAL-FEE + WS-REVIEW-FEE
           END-IF.

       COMPUTE-TOTAL-DEBIT.
      * R-WP-007: total debit to the originating account is the wire
      * amount plus the total fee.
           COMPUTE WS-TOTAL-DEBIT = WS-AMOUNT + WS-TOTAL-FEE.

       RESOLVE-VALUE-DATE.
      * R-WP-008: wires submitted strictly before the 15:00 domestic
      * cutoff settle same-day (offset 0); at or after cutoff, next
      * business day (offset 1). HHMM is compared as a 4-digit number,
      * which is valid exactly because both HH and MM are always
      * exactly 2 digits wide (00-23 / 00-59).
           COMPUTE WS-SUBMIT-HHMM = (WS-SUBMIT-HH-NUM * 100)
                                     + WS-SUBMIT-MM-NUM.
           IF WS-SUBMIT-HHMM >= WS-CUTOFF-HHMM
               MOVE 1 TO WS-VALUE-DATE-OFFSET
           ELSE
               MOVE 0 TO WS-VALUE-DATE-OFFSET
           END-IF.

       BUILD-OUTPUT.
           MOVE WS-TOTAL-FEE   TO WS-OUT-FEE-X.
           MOVE WS-TOTAL-DEBIT TO WS-OUT-DEBIT-X.
           STRING WS-STATUS            DELIMITED BY SIZE
                  "|"                  DELIMITED BY SIZE
                  WS-REJECT-REASON     DELIMITED BY SIZE
                  "|"                  DELIMITED BY SIZE
                  WS-OUT-FEE-X         DELIMITED BY SIZE
                  "|"                  DELIMITED BY SIZE
                  WS-OUT-DEBIT-X       DELIMITED BY SIZE
                  "|"                  DELIMITED BY SIZE
                  WS-VALUE-DATE-OFFSET DELIMITED BY SIZE
               INTO WS-OUT-LINE.
