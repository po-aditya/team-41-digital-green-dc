# Requirements Document

## Introduction

JAAK is a voice survey agent for the Digital Green FarmerChat MEL Survey Agent. This spec covers the text-only core dialogue engine (JAAK_Engine). Given one Survey and one Farmer_Record, the engine walks the farmer through the survey one question at a time, maps each transcribed answer to an allowed option value or scale number, and ends by producing one Response_Record that validates against `response.schema.json`.

JAAK reads the survey as given. It never writes its own questions, never gives agronomic advice, and never asks for personal information.

Audio (speech-to-text, text-to-speech), phone calls, Streamlit, survey generation, scheduling, the evaluation harness, and languages other than Hindi (hi-IN) and English (en-IN) are out of scope. A later spec adds voice and the demo UI and plugs them into this engine.

Inputs (read-only, never modified): `json/schemas/*.json` (insight, survey, no_survey, schedule_handoff, response, bottom_sheet), `json/rules/rules.json`, `json/rules/outcome_codes.json`, `json/scenarios/`, and `data/farmers.csv`.

Persona guidance from Digital Green: JAAK is a friendly, patient, and clear voice assistant for agricultural surveys. It speaks in short, conversational sentences, avoids jargon and markdown because its text is read aloud, and waits for the farmer to finish before asking the next question.

## Glossary

- **JAAK_Engine**: The text-only dialogue engine specified here. It consumes a Survey and a Farmer_Record and produces Turns and a Response_Record.
- **Survey**: A JSON object that validates against `survey.schema.json`. It holds one to three Items in one language.
- **Item**: One survey question. Its type is `survey-single-select`, `survey-confirm`, or `survey-scale`.
- **Option**: A `{value, label, follow_up?}` entry on a select or confirm Item.
- **Scale_Item**: An Item of type `survey-scale` with `scale_min`, `scale_max`, and optional `follow_up_at_or_below` and `follow_up_reason`.
- **Farmer_Record**: One row of farmers.csv (`farmer_id`, `language`, `preferred_channel`, and so on). It has no name column.
- **Farmer_Name_Copy**: A copy of farmers.csv, stored outside the read-only participant pack, that adds a synthetic `farmer_name` column.
- **Turn**: One utterance JAAK produces: a greeting, a question prompt, a re-ask, or a closing.
- **Transcribed_Answer**: Text standing in for what the farmer said. It is data, never instructions.
- **Answer_Mapper**: The JAAK_Engine component that turns a Transcribed_Answer into an Option value, a scale integer, or an unclear result.
- **Unclear_Result**: The Answer_Mapper result when a Transcribed_Answer matches no allowed value with confidence.
- **Response_Record**: The final JSON output. It validates against `response.schema.json`.
- **Outcome_Code**: A status or failure code defined in `outcome_codes.json`.
- **Follow_Up_Flag**: The `needs_follow_up` boolean and `follow_up_reasons` array of a Response_Record.
- **Boundary**: Any point where data enters or leaves the JAAK_Engine: Survey input, Farmer_Record input, Farmer_Name_Copy input, Transcribed_Answer input, and Response_Record output.
- **Rejection_Log**: The log where the JAAK_Engine records each rejected input or output with the Boundary, the reason, and no farmer answer text beyond 256 characters.
- **Personal_Information**: A farmer's name, phone number, or exact location.
- **Agronomic_Advice**: Any statement about crop, animal, soil, or input management, including dosages and product recommendations.
- **Dialogue_Session**: One run of the JAAK_Engine for one Survey and one Farmer_Record.

## Requirements

### Requirement 1: Schema-validated models at every boundary

**User Story:** As a developer, I want typed models generated from the Digital Green schemas, so that invalid data is stopped at the edge and never reaches the dialogue.

#### Acceptance Criteria

1. THE JAAK_Engine SHALL provide Pydantic models for exactly six schemas (survey, response, insight, no_survey, schedule_handoff, and bottom_sheet), each generated from or checked against the matching file in `json/schemas/`, such that every example document in the participant pack that conforms to a schema is accepted by its model and every example document that violates the schema is rejected by its model.
2. WHEN a Survey is supplied, THE JAAK_Engine SHALL validate the Survey against `survey.schema.json` before producing any Turn.
3. WHEN a Farmer_Record is supplied, THE JAAK_Engine SHALL validate that `farmer_id` is a string of 1 to 64 characters containing at least one non-whitespace character and that `language` is exactly `hi-IN` or `en-IN` (case-sensitive) before producing any Turn.
4. IF a Survey or Farmer_Record fails validation, THEN THE JAAK_Engine SHALL reject the input, write exactly one Rejection_Log entry naming the Boundary and the JSON path of every failing field, return an error to the caller identifying the Boundary that rejected the input, and produce zero Turns.
5. WHEN the JAAK_Engine builds a Response_Record, THE JAAK_Engine SHALL validate the Response_Record against `response.schema.json` before returning it.
6. IF a built Response_Record fails validation, THEN THE JAAK_Engine SHALL write exactly one Rejection_Log entry naming the Boundary and the failing field paths, raise an error, and return no Response_Record to the caller.
7. IF the Survey `farmer_id` differs from the Farmer_Record `farmer_id` (exact, case-sensitive string comparison), THEN THE JAAK_Engine SHALL reject the pair, write exactly one Rejection_Log entry naming the Boundary and both `farmer_id` values, and produce zero Turns.
8. THE JAAK_Engine SHALL leave every file under `data/participant-pack/` byte-for-byte unchanged, verified by identical SHA-256 digests of all files before and after any validation, Turn production, or Response_Record build.

### Requirement 2: Greeting

**User Story:** As a farmer, I want to hear one short line on why JAAK is calling, so that I know what the call is about before any question.

#### Acceptance Criteria

1. WHEN a Dialogue_Session starts, THE JAAK_Engine SHALL produce exactly one greeting Turn before the first question Turn and SHALL NOT produce a question Turn until the greeting Turn has been produced.
2. THE greeting Turn SHALL consist of one or two sentences of at most 20 words each, SHALL contain the name "JAAK", SHALL state that the call is a short survey about advice the farmer received from FarmerChat, and SHALL end with the final sentence "Is now a good time?" in en-IN or the fixed hi-IN equivalent from the same template, so that the greeting Turn complies with Requirement 7 criterion 5.
3. THE greeting Turn SHALL be written entirely in the Survey `language`.
4. THE greeting Turn SHALL contain no Agronomic_Advice, no text copied from `rationale`, and no text copied from any Insight field.
5. IF the Survey `language` is missing or is not a language JAAK_Engine supports, THEN THE JAAK_Engine SHALL NOT start the Dialogue_Session, SHALL produce no greeting Turn and no question Turn, and SHALL return an error indicating that the language is unavailable.
6. IF the greeting Turn cannot be produced, THEN THE JAAK_Engine SHALL NOT produce any question Turn, SHALL end the Dialogue_Session, and SHALL return an error indicating that the greeting failed.

### Requirement 3: Language selection

**User Story:** As a farmer, I want JAAK to speak my language without asking me which one, so that the call starts without friction.

#### Acceptance Criteria

1. THE JAAK_Engine SHALL support exactly two languages, `hi-IN` and `en-IN`, and no others.
2. WHEN a Survey is received, THE JAAK_Engine SHALL set the session language to the Survey `language` field value before producing the first JAAK-authored Turn.
3. WHEN the Survey `language` is `hi-IN` or `en-IN`, THE JAAK_Engine SHALL produce 100% of JAAK-authored Turns in that language for the whole session, with no Turn in the other supported language.
4. IF the Survey `language` is missing, empty, or any value other than exactly `hi-IN` or `en-IN` (case-sensitive match), THEN THE JAAK_Engine SHALL reject the Survey, SHALL produce no Turn, SHALL write exactly one Rejection_Log entry that states the rejection reason and the received `language` value, and SHALL leave no Response_Record for that Survey.
5. WHEN the Survey `language` is a supported value that differs from the Farmer_Record `language`, THE JAAK_Engine SHALL use the Survey `language` and SHALL write exactly one warning entry to the Rejection_Log that states both language values, without rejecting the Survey.
6. THE JAAK_Engine SHALL contain no Turn that asks the farmer which language to use, or offers a choice of language, in any session.
7. WHEN a Response_Record is written for a session, THE JAAK_Engine SHALL set the Response_Record `language` to a value exactly equal to the Survey `language`, including when the Farmer_Record `language` differs.

### Requirement 4: Greeting personalisation

**User Story:** As a farmer, I want to be greeted by name when the system already has a synthetic name, so that the call feels personal without JAAK asking for anything.

#### Acceptance Criteria

1. WHERE a Farmer_Name_Copy is configured, WHEN the JAAK_Engine produces the greeting Turn for a Farmer_Record whose `farmer_name` in the Farmer_Name_Copy is non-empty (1 to 100 characters after trimming leading and trailing whitespace), THE JAAK_Engine SHALL include that `farmer_name` exactly once in the greeting Turn, matched to the Farmer_Record by `farmer_id`, as the greeting-only text source permitted by Requirement 16 criterion 1, and THE JAAK_Engine SHALL use the `farmer_name` only if, after trimming, it has at most 3 whitespace-separated tokens, at most 100 characters, and contains no digits, `@`, markdown characters, sentence punctuation, or control characters; otherwise THE JAAK_Engine SHALL treat the `farmer_name` as absent and criterion 3 applies.
2. WHERE no Farmer_Name_Copy is configured, WHEN the JAAK_Engine produces the greeting Turn, THE JAAK_Engine SHALL produce a greeting Turn that contains no name.
3. IF the Farmer_Name_Copy has no entry for the Farmer_Record `farmer_id`, or the `farmer_name` is empty or contains only whitespace, THEN THE JAAK_Engine SHALL produce a greeting Turn that contains no name and SHALL continue the call without raising an error to the farmer.
4. THE JAAK_Engine SHALL contain no Turn that asks the farmer to state, confirm, or correct a name.
5. THE JAAK_Engine SHALL include the `farmer_name` in no Turn other than the greeting Turn, across all Turns of a call from greeting to call end.
6. THE JAAK_Engine SHALL store the `farmer_name` in no field of the Response_Record.
7. THE JAAK_Engine SHALL open the Farmer_Name_Copy for read access only and SHALL leave `data/participant-pack/data/farmers.csv` byte-for-byte unchanged after any call.

### Requirement 5: One question at a time

**User Story:** As a farmer, I want questions one by one with my choices read back, so that I can answer without losing track.

#### Acceptance Criteria

1. WHEN the greeting reply step defined in criterion 10 is complete, THE JAAK_Engine SHALL produce the question Turn for the first Item in Survey `items` order.
2. THE JAAK_Engine SHALL present exactly one Item per question Turn.
3. WHEN an Item is answered, skipped, or marked invalid, THE JAAK_Engine SHALL produce the question Turn for the next Item in Survey `items` order.
4. IF an Item is the last Item in Survey `items` order, THEN WHEN that Item is answered, skipped, or marked invalid, THE JAAK_Engine SHALL produce no further question Turn and SHALL signal that the Survey has no remaining Items.
5. THE JAAK_Engine SHALL produce no question Turn for an Item before the farmer's answer to the preceding Item has been resolved, where resolved means the preceding Item has been recorded as answered, skipped, or invalid.
6. WHEN a question Turn is produced for a select or confirm Item, THE question Turn SHALL contain the Item `prompt` followed by every Option `label` of that Item, in Survey order, with no Option omitted, reordered, or repeated.
7. WHEN a question Turn is produced for a Scale_Item, THE question Turn SHALL contain the Item `prompt` followed by the range from `scale_min` to `scale_max`, with both bounds stated.
8. WHEN the JAAK_Engine produces a Turn that waits for an answer, THE JAAK_Engine SHALL accept the Transcribed_Answer only after the caller marks the farmer's utterance as complete.
9. IF a Transcribed_Answer is submitted before the caller marks the farmer's utterance as complete, THEN THE JAAK_Engine SHALL ignore the submission, SHALL keep the current Item unresolved, and SHALL produce no question Turn for the next Item.
10. WHEN the greeting Turn has been produced, THE JAAK_Engine SHALL wait for exactly one caller-marked reply (a Transcribed_Answer submitted with the utterance marked complete, or a caller-signalled timeout) before producing any question Turn.
11. WHEN the greeting reply is a not-now phrase (which includes a plain "no" and its Hindi equivalents, for example "नहीं", "nahi", and "nahin"), THE JAAK_Engine SHALL end the Dialogue_Session as defined in Requirement 11 criterion 4; WHEN it is an opt-out phrase, as defined in Requirement 11 criterion 5; WHEN it is any other reply, or the caller signals a timeout, THE JAAK_Engine SHALL move to the first Item. The greeting reply SHALL NOT be treated as an answer to any Item, SHALL NOT be stored in any Response_Record field (including `raw_input`, `answers`, and `items`), and SHALL NOT count as an attempt for any Item. A timeout on the greeting reply SHALL NOT trigger the re-ask rule in Requirement 11 criterion 1.

### Requirement 6: Survey text fidelity

**User Story:** As a Digital Green reviewer, I want JAAK to ask exactly what the survey says, so that answers stay comparable across farmers.

#### Acceptance Criteria

1. WHEN the JAAK_Engine produces a question Turn, THE JAAK_Engine SHALL render the Survey Item `prompt` field as a character-for-character copy of the stored value, with 0 characters added, removed, substituted, reordered, or re-cased, and with no whitespace changes.
2. WHEN the JAAK_Engine produces a question Turn that lists options, THE JAAK_Engine SHALL render each Survey Option `label` field as a character-for-character copy of the stored value, with 0 characters added, removed, substituted, reordered, or re-cased.
3. WHEN the JAAK_Engine produces a question Turn that lists options, THE JAAK_Engine SHALL present the options in the same order as the Survey Option order stored for the Survey Item, and SHALL present all stored options with none omitted.
4. THE JAAK_Engine SHALL contain no function that creates, edits, translates, or reorders Items, Options, prompts, or labels.
5. WHEN the JAAK_Engine produces a question Turn, THE JAAK_Engine SHALL add only text drawn from a fixed template set for the session language, limited to connective text such as the lead-in to the option list, and SHALL add no other text.
6. THE fixed template set SHALL contain no Agronomic_Advice and no Personal_Information, and each template SHALL be at most 200 characters.
7. IF the Survey Item `prompt` is empty or missing, or any Survey Option `label` of that Item is empty or missing, THEN THE JAAK_Engine SHALL NOT produce the question Turn, SHALL NOT substitute generated text, SHALL leave the session state unchanged, and SHALL report an error indicating the missing survey text to the caller.
8. IF no fixed template exists for the session language, THEN THE JAAK_Engine SHALL NOT produce the question Turn, SHALL NOT translate or generate substitute text, and SHALL report an error indicating the unsupported session language to the caller.

### Requirement 7: Voice style

**User Story:** As a farmer listening on a phone, I want short, clear sentences, so that I can follow what JAAK says.

#### Acceptance Criteria

1. THE JAAK_Engine SHALL write every fixed template, which is the JAAK-authored text of every Turn, without markdown characters (`*`, `_` used as emphasis, `#`, backticks, `>`, list markers, and table pipes) and without emoji; verbatim Survey prompts and labels are not JAAK-authored text and are governed by Requirement 6.
2. THE JAAK_Engine SHALL write every sentence of JAAK-authored template text with at most 20 words, where a word is a run of non-whitespace characters separated by whitespace and a sentence ends at a period, question mark, or text end; this limit SHALL NOT apply to verbatim Survey prompts and labels.
3. THE JAAK_Engine SHALL write the JAAK-authored template text of every Turn with at least 1 and at most 4 sentences; this limit SHALL NOT apply to verbatim Survey prompts and labels.
4. THE JAAK_Engine SHALL contain no URL (any text beginning with `http://`, `https://`, or `www.`) and no technical identifier (such as `survey_id`, `item_id`, or an option `value`) in the JAAK-authored template text of any Turn.
5. WHEN the JAAK_Engine produces a Turn other than the closing Turn, THE JAAK_Engine SHALL end the JAAK-authored template text of that Turn with a question mark as the final character, with the question awaiting a farmer answer.
6. WHEN the JAAK_Engine produces the closing Turn, THE JAAK_Engine SHALL include a thanks to the farmer in the final sentence and SHALL NOT end the Turn with a question.
7. WHEN the JAAK_Engine loads the fixed template set, THE JAAK_Engine SHALL validate every fixed template against criteria 1 to 6, and IF any template violates a criterion, THEN THE JAAK_Engine SHALL fail at load time with an error naming the template and the violated criterion and SHALL NOT start any Dialogue_Session.

### Requirement 8: Answer mapping for select and confirm Items

**User Story:** As a MEL analyst, I want each spoken answer mapped to exactly one allowed option value, so that answers can be compared across farmers.

#### Acceptance Criteria

1. WHEN a Transcribed_Answer for a select or confirm Item, after normalization under criterion 2, equals exactly one Option `label` or `value` of that Item after the same normalization, THE Answer_Mapper SHALL return that Option `value`.
2. THE Answer_Mapper SHALL ignore letter case, leading and trailing whitespace (spaces, tabs, line breaks), and trailing punctuation (one or more of `. , ! ? ; : ।`) when matching.
3. THE Answer_Mapper SHALL match Hindi answers written in Devanagari script and, for the Hindi yes and no words only, their Roman-script spellings (for example "haan" and "nahi"), using the same matching rules as criterion 1.
4. IF a normalized Transcribed_Answer equals the normalized `label` or `value` of more than one Option, THEN THE Answer_Mapper SHALL return an Unclear_Result and SHALL NOT return any Option `value`.
5. IF a normalized Transcribed_Answer equals no Option `label` or `value`, including when the Transcribed_Answer is empty or contains only whitespace and punctuation, THEN THE Answer_Mapper SHALL return an Unclear_Result and SHALL NOT return any Option `value`.
6. THE Answer_Mapper SHALL return either one `value` that exists in the Item's Options or an Unclear_Result, and nothing else.
7. WHEN the Answer_Mapper receives the same Item and the same Transcribed_Answer more than once, THE Answer_Mapper SHALL return an identical result each time.

### Requirement 9: Answer mapping for scale Items

**User Story:** As a MEL analyst, I want spoken numbers mapped to the scale range, so that scale answers are valid integers.

#### Acceptance Criteria

1. WHEN a Transcribed_Answer for a Scale_Item contains exactly one distinct number, expressed as a digit string or as a number word in the session language, and that number is an integer from `scale_min` to `scale_max` inclusive, THE Answer_Mapper SHALL return that integer.
2. THE Answer_Mapper SHALL recognise the English number words and the Hindi number words for every integer from 0 to `scale_max`, for `scale_max` from 1 to 10 inclusive.
3. WHEN a Transcribed_Answer for a Scale_Item contains exactly one distinct number and that number is an integer below `scale_min` or above `scale_max`, THE Answer_Mapper SHALL return an Unclear_Result.
4. WHEN a Transcribed_Answer for a Scale_Item contains two or more different numbers, THE Answer_Mapper SHALL return an Unclear_Result.
5. WHEN a Transcribed_Answer for a Scale_Item contains the same number more than once (for example "4, four"), THE Answer_Mapper SHALL treat it as one distinct number and apply criteria 1 and 3.
6. WHEN a Transcribed_Answer for a Scale_Item contains no number, is empty, or contains only whitespace, THE Answer_Mapper SHALL return an Unclear_Result.
7. WHEN a Transcribed_Answer for a Scale_Item contains a non-integer number (for example "3.5" or "three and a half"), THE Answer_Mapper SHALL return an Unclear_Result.
8. THE Answer_Mapper SHALL return, for a Scale_Item, either a single integer from `scale_min` to `scale_max` inclusive or an Unclear_Result, and no other value.

### Requirement 10: Re-ask once, then record the outcome

**User Story:** As a farmer, I want one more chance when JAAK does not understand me, so that a single mumble does not lose my answer.

#### Acceptance Criteria

1. WHEN the Answer_Mapper returns an Unclear_Result for the first attempt on an Item, THE JAAK_Engine SHALL produce exactly one re-ask Turn that restates all of the Item's Option labels (or the scale range minimum and maximum for a scale Item) and then wait for a second Transcribed_Answer.
2. WHEN the Answer_Mapper returns a valid value on the second attempt, THE JAAK_Engine SHALL accept that value, set the Item `result` to answered, and set the Item `attempts` to 2.
3. WHEN the Answer_Mapper returns an Unclear_Result on the second attempt, THE JAAK_Engine SHALL mark the Item `result` as `invalid`, set `value` to null, set `attempts` to 2, and move to the next Item, or complete the Survey if the Item is the last one.
4. THE JAAK_Engine SHALL ask any one Item at most twice, and SHALL NOT produce a third prompt or a second re-ask Turn for the same Item; the advice-decline and re-prompt repeats defined in Requirement 16 criterion 7 are not asks and do not count toward this limit.
5. WHEN an Item is marked `invalid` after two Unclear_Results, THE JAAK_Engine SHALL record the failure code `speech_not_understood` for that Item, using the Outcome_Code value defined for it in `outcome_codes.json`.
6. THE JAAK_Engine SHALL NOT store an answer value for an Item from any attempt for which the Answer_Mapper returned an Unclear_Result, so that the stored `value` is null unless a later attempt on the same Item returned a valid value.
7. WHEN the re-ask Turn is produced, THE JAAK_Engine SHALL build the re-ask Turn text only from the Item `prompt`, the Option `label` text from the Survey, and the fixed templates, and SHALL NOT include any other generated or free-form text.
8. WHEN the caller signals a timeout on an Item, THE JAAK_Engine SHALL apply Requirement 11 criteria 1 and 2, which are the only statement of the timeout rule.

### Requirement 11: Non-answer outcomes

**User Story:** As a MEL analyst, I want every kind of non-answer recorded with the correct outcome code, so that retries and caps work as Digital Green defined.

#### Acceptance Criteria

1. WHEN the caller signals a timeout for the first time on an Item (the farmer gave no response to the Item prompt), THE JAAK_Engine SHALL re-ask that Item once and set the Item `attempts` to 2.
2. WHEN the caller signals a timeout on an Item that has already been re-asked (a second caller-signalled timeout, or a first timeout on the re-ask that followed an Unclear_Result), THE JAAK_Engine SHALL mark the Item `result` as `skipped` with `attempts` 2 and move to the next Item, or end the Dialogue_Session if no Item remains.
3. WHEN the farmer asks to skip an Item, THE JAAK_Engine SHALL mark that Item `result` as `skipped` and move to the next Item, or end the Dialogue_Session if no Item remains.
4. WHEN the farmer says not now, THE JAAK_Engine SHALL end the Dialogue_Session and produce a Response_Record with status `declined` and `failure_code` `farmer_declined`.
5. WHEN the farmer asks for no more surveys, THE JAAK_Engine SHALL end the Dialogue_Session and produce a Response_Record with status `declined` and `failure_code` `farmer_opted_out`.
6. WHEN the caller reports that the call dropped after at least one Item was resolved, THE JAAK_Engine SHALL produce a Response_Record with `failure_code` `voice_call_dropped` and keep the answers already accepted.
7. IF the caller reports that the call dropped before any Item was resolved, THEN THE JAAK_Engine SHALL produce a Response_Record with `failure_code` `voice_call_dropped` and an empty `answers` collection.
8. WHEN the caller reports that nobody picked up, THE JAAK_Engine SHALL produce a Response_Record with `failure_code` `voice_no_answer`.
9. WHEN the caller reports that the line was busy, THE JAAK_Engine SHALL produce a Response_Record with `failure_code` `voice_busy`.
10. WHEN the caller reports that the survey window has ended, THE JAAK_Engine SHALL produce a Response_Record with `failure_code` `window_expired`.
11. WHEN the caller reports that the answering identity belongs to a different farmer, THE JAAK_Engine SHALL produce a Response_Record with `failure_code` `identity_mismatch` and `answered_by` set to the reported identity.
12. WHEN the caller reports a repeat answer to an already answered survey, THE JAAK_Engine SHALL produce a Response_Record with `failure_code` `duplicate_answer`.
13. WHEN the JAAK_Engine produces a Response_Record with a `failure_code`, THE JAAK_Engine SHALL copy `status`, `retry_decision`, `retry_after_minutes`, and `counts_toward_cap` unchanged from the entry in `outcome_codes.json` that matches the `failure_code` for the `voice` channel.
14. IF a `failure_code` is not listed for the `voice` channel in `outcome_codes.json`, THEN THE JAAK_Engine SHALL reject the request, produce no Response_Record, and write exactly one Rejection_Log entry identifying the unlisted `failure_code`.
15. THE JAAK_Engine SHALL set `sheet_outcome` to null in every Response_Record.
16. WHEN a Response_Record is produced from a status other than `completed`, `partial`, or `negative_outcome`, THE JAAK_Engine SHALL set `answers` to the answers accepted before the outcome, which MAY be empty.

### Requirement 12: Success statuses and completeness

**User Story:** As a MEL analyst, I want the record to say clearly whether the survey was completed, partial, or flagged, so that reporting is consistent.

#### Acceptance Criteria

1. WHEN the Dialogue_Session ends and every Item has `result` `answered` and no Follow_Up_Flag reason applies, THE JAAK_Engine SHALL produce a Response_Record with status `completed`, `complete` true, and `failure_code` null.
2. WHEN the Dialogue_Session ends and at least one Item has `result` `answered` and at least one other Item has `result` `skipped`, `invalid`, or `not_reached`, and no Follow_Up_Flag reason applies, THE JAAK_Engine SHALL produce a Response_Record with status `partial`, `complete` false, and `failure_code` null.
3. WHEN the Dialogue_Session ends and at least one accepted answer triggers a Follow_Up_Flag reason, THE JAAK_Engine SHALL produce a Response_Record with status `negative_outcome`, regardless of whether the remaining Items are answered, skipped, invalid, or not_reached (so `negative_outcome` takes precedence over `partial`), and with `failure_code` null.
4. WHEN the Dialogue_Session ends with zero Items having `result` `answered` and no caller-reported failure, THE JAAK_Engine SHALL produce a Response_Record with `complete` false and the failure status and Outcome_Code for the end reason: `farmer_declined` or `farmer_opted_out` per Requirement 11 criteria 4 and 5, or `speech_not_understood` per Requirement 10 criterion 5 when at least one Item is invalid and none is answered.
5. THE JAAK_Engine SHALL populate the Response_Record `items` array with exactly one entry per Survey Item, ordered by Survey order, including Items with `result` `skipped`, `invalid`, or `not_reached`.
6. THE JAAK_Engine SHALL populate the Response_Record `answers` object with a key for an `item_id` if and only if that Item `result` is `answered`, and SHALL leave `answers` empty when no Item is answered.
7. WHEN a Response_Record has status `completed`, `partial`, or `negative_outcome`, THE JAAK_Engine SHALL set `retry_decision` to `none`, `retry_after_minutes` to null, `counts_toward_cap` to true, and `farmerchat_reply` to null.
8. WHEN a Response_Record has a `failure_code`, THE JAAK_Engine SHALL copy `counts_toward_cap` unchanged from `outcome_codes.json` per Requirement 11 criterion 13 and SHALL NOT recompute it from whether the farmer was asked an Item.
9. THE JAAK_Engine SHALL set Response_Record `complete` to true if and only if every Item `result` is `answered`, and false in all other cases.
10. IF the Item results satisfy more than one status criterion, THEN THE JAAK_Engine SHALL assign exactly one status using this precedence: failure status per criterion 4, then `negative_outcome`, then `partial`, then `completed`.

### Requirement 13: Bad-outcome flagging

**User Story:** As a FarmerChat support lead, I want answers that signal failed advice or harm flagged for follow-up, so that farmers who need help are reached.

#### Acceptance Criteria

1. WHEN an accepted answer to a select or confirm Item equals the `value` of an Option that has a non-empty `follow_up` reason, THE JAAK_Engine SHALL add that reason to `follow_up_reasons` for the Response_Record.
2. WHEN an accepted answer to a Scale_Item is a number less than or equal to the Item's `follow_up_at_or_below` threshold, THE JAAK_Engine SHALL add the Item's `follow_up_reason` to `follow_up_reasons` for the Response_Record.
3. WHEN the Response_Record is produced AND `follow_up_reasons` contains at least one reason, THE JAAK_Engine SHALL set `needs_follow_up` to true.
4. WHEN the Response_Record is produced AND `follow_up_reasons` contains zero reasons, THE JAAK_Engine SHALL set `needs_follow_up` to false.
5. THE JAAK_Engine SHALL list each distinct follow-up reason exactly once in `follow_up_reasons`, ordered by the position of its first occurrence in the Survey Item sequence, even if multiple answers trigger the same reason.
6. THE JAAK_Engine SHALL derive follow-up reasons only from the Survey fields `follow_up`, `follow_up_at_or_below` and `follow_up_reason`, and SHALL NOT derive them from Transcribed_Answer text, sentiment or keywords.
7. IF an Item's answer was not accepted (including rejected, unmatched, skipped, or unanswered answers), THEN THE JAAK_Engine SHALL add zero follow-up reasons for that Item.
8. IF the JAAK_Engine produces a Response_Record with a failure status, THEN THE JAAK_Engine SHALL set `needs_follow_up` to false and `follow_up_reasons` to an empty array, discarding any reasons collected earlier in the same survey.
9. WHEN a farmer gives an accepted answer that triggers a follow-up reason, THE JAAK_Engine SHALL present the next Item in the Survey sequence (or complete the survey if none remains) AND SHALL NOT include advice, comment, or acknowledgement of the trigger in any message sent to the farmer.
10. IF an Item has no `follow_up_reason` defined or a `follow_up_reason` that is empty AND its answer would otherwise trigger a flag, THEN THE JAAK_Engine SHALL add zero reasons for that Item and SHALL leave `follow_up_reasons` unchanged.

### Requirement 14: Closing

**User Story:** As a farmer, I want a polite thanks at the end, so that the call ends well.

#### Acceptance Criteria

1. WHEN every Item has been resolved, THE JAAK_Engine SHALL produce exactly one closing Turn that thanks the farmer.
2. THE closing Turn SHALL be written in the session language.
3. THE closing Turn SHALL contain no Agronomic_Advice, no mention of the answers given, and no further question or request for a response from the farmer.
4. WHEN the Dialogue_Session ends because the farmer declined or opted out, THE JAAK_Engine SHALL produce exactly one closing Turn, written in the session language, that acknowledges the farmer's choice, says goodbye, and contains no Agronomic_Advice, no request to reconsider, and no further question.
5. WHEN a closing Turn is produced, THE JAAK_Engine SHALL produce the Response_Record after that closing Turn and SHALL NOT produce any further Turn after the closing Turn.
6. WHEN the Dialogue_Session ends because of a caller-reported failure with no live farmer (`voice_no_answer`, `voice_busy`, `voice_call_dropped`, `window_expired`), THE JAAK_Engine SHALL produce no closing Turn and SHALL still produce the Response_Record recording the reported failure reason.
7. IF a required closing Turn cannot be produced in the session language or cannot be delivered, THEN THE JAAK_Engine SHALL still produce the Response_Record, SHALL record the closing-not-delivered indicator in the session-end log entry required by Requirement 19 criterion 5, and SHALL NOT record that indicator in any Response_Record field.

### Requirement 15: Response record fields and traceability

**User Story:** As a developer, I want every record to carry stable keys and timestamps, so that retries and duplicates can be told apart.

#### Acceptance Criteria

1. THE JAAK_Engine SHALL set the Response_Record `survey_id`, `farmer_id`, and `source_insight_ids` to values equal to those of the Survey, with `source_insight_ids` preserving the same elements in the same order.
2. THE JAAK_Engine SHALL set the Response_Record `channel` to `voice` for every Response_Record it produces.
3. THE JAAK_Engine SHALL set the Response_Record `response_key` to a string of 1 to 64 characters that is unique for each combination of `survey_id`, `channel`, and `delivery_attempt`, and that is identical when the same combination is produced again.
4. THE JAAK_Engine SHALL set the Response_Record `delivery_attempt` to the integer supplied by the caller, or to 1 when the caller supplies none.
5. IF the caller supplies a `delivery_attempt` that is not an integer from 1 to 5 inclusive, THEN THE JAAK_Engine SHALL reject the request with an error indicating the invalid `delivery_attempt` and SHALL NOT produce a Response_Record.
6. THE JAAK_Engine SHALL set each non-null `timestamps` value and `recorded_at` to an ISO 8601 date-time with the `+05:30` offset, and `recorded_at` SHALL NOT be null.
7. THE JAAK_Engine SHALL take every time value from a caller-supplied clock, so that a fixed clock produces identical `timestamps` and `recorded_at` values on repeated runs.
8. IF a `raw_event` value longer than 256 characters is to be recorded, THEN THE JAAK_Engine SHALL truncate it to its first 256 characters before setting it on the Response_Record.
9. WHEN the farmer's answer was accepted, THE JAAK_Engine SHALL set the Response_Record `answered_by` to the `farmer_id`.
10. IF no answer was accepted, THEN THE JAAK_Engine SHALL set the Response_Record `answered_by` to null, except as set by Requirement 11 criterion 11.
11. FOR ALL valid Response_Records produced by the JAAK_Engine, serialising to JSON and parsing back with the Pydantic model SHALL produce an equal Response_Record (round-trip property).
12. THE JAAK_Engine SHALL set `input_kind` to `speech`, and not `keypad`, for every Response_Record item whose answer was accepted from a Transcribed_Answer.

### Requirement 16: Hard rule, no agronomic advice

**User Story:** As Digital Green, I want JAAK never to give agricultural advice, so that farmers only receive vetted guidance from FarmerChat.

#### Acceptance Criteria

1. THE JAAK_Engine SHALL produce the text of every Turn only from four sources: the Survey Item `prompt` text, the Survey Option `label` text, the fixed template set, and the `farmer_name` in the greeting Turn only, with no other text in the Turn.
2. WHEN the farmer sends a message that asks a question about crops, animals, dosages, pesticides, fertilizers, seeds, or other agricultural products, THE JAAK_Engine SHALL reply with a fixed template stating that JAAK cannot give agricultural advice and that FarmerChat can help, and SHALL then repeat the current Item in the same Turn sequence.
3. WHEN the JAAK_Engine replies with the no-advice template, THE JAAK_Engine SHALL keep the current Item unanswered and SHALL NOT record the farmer's question as an answer to that Item.
4. IF the JAAK_Engine cannot determine whether a farmer message is an agricultural question or an answer to the current Item, THEN THE JAAK_Engine SHALL treat the message as an invalid answer, reply with the fixed re-prompt template, and repeat the current Item, without generating any advice text.
5. THE JAAK_Engine SHALL contain no call to a language model or any other generator of free text for the text of a Turn.
6. THE JAAK_Engine SHALL include no Insight `summary`, `rationale`, or advice text in any Turn.
7. THE JAAK_Engine SHALL allow at most 2 repeats per Item in total, counting advice-decline repeats (criterion 2) and re-prompt repeats (criterion 4) together; these repeats SHALL NOT count as attempts toward the two-attempt cap in Requirement 10 criterion 4 and SHALL NOT change the Item `attempts`.
8. WHEN the repeat cap in criterion 7 is reached for an Item and a further advice question or undeterminable message arrives, THE JAAK_Engine SHALL mark the Item `result` as `invalid` with `value` null, record the failure code `speech_not_understood` for that Item, handled the same way as Requirement 10 criterion 5 (using the Outcome_Code values defined for it in `outcome_codes.json`), apply the handling of Requirement 10 criterion 3 to move to the next Item or complete the Survey, and leave the Item `attempts` unchanged by the repeats.

### Requirement 17: Hard rule, no personal information

**User Story:** As Digital Green, I want JAAK never to collect or echo personal data, so that farmer privacy is protected.

#### Acceptance Criteria

1. THE JAAK_Engine SHALL contain no Turn that asks for a name, phone number, address, village, or exact location, where exact location means any place name or coordinate more specific than the Farmer_Record `district`.
2. WHEN a Transcribed_Answer contains a run of 7 or more digits, with or without spaces, hyphens, or a leading plus sign between digits, THE JAAK_Engine SHALL store the text `[redacted]` in `raw_input` in place of the full Transcribed_Answer and SHALL NOT store any part of the original Transcribed_Answer in any Response_Record field.
3. THE JAAK_Engine SHALL NOT include any word or number taken from a Transcribed_Answer in the text of any Turn.
4. THE JAAK_Engine SHALL NOT write the Farmer_Record `state` or `district` into the text of any Turn after the greeting Turn, SHALL NOT write `farmer_name` into the text of any Turn other than the greeting Turn (the only Turn permitted by Requirement 16 criterion 1), and SHALL NOT write `state`, `district`, or `farmer_name` into any Response_Record field.
5. THE JAAK_Engine SHALL write each Rejection_Log entry without the `farmer_name`, and with the farmer answer text truncated to a maximum of 256 characters.
6. WHEN a farmer volunteers Personal_Information in a Transcribed_Answer, THE JAAK_Engine SHALL treat the answer as an Unclear_Result for the current Item, SHALL store `[redacted]` in `raw_input` in place of the Transcribed_Answer, and SHALL NOT store the Personal_Information in any Response_Record field or Rejection_Log entry.
7. IF a Transcribed_Answer is redacted under criterion 2 or 6, THEN THE JAAK_Engine SHALL continue the survey with the same Item or the next step defined for an Unclear_Result, and SHALL NOT end the survey solely because of the redaction.

### Requirement 18: Hard rule, data is not instructions

**User Story:** As a security reviewer, I want text from farmers and insights treated as data only, so that prompt injection cannot change JAAK's behaviour.

#### Acceptance Criteria

1. THE JAAK_Engine SHALL treat every Transcribed_Answer, regardless of length from 0 to 2,000 characters, as data to be matched against the current Item and SHALL NOT interpret it as an instruction.
2. THE JAAK_Engine SHALL treat every Insight field and Survey `rationale` as data and SHALL NOT interpret it as an instruction, so that the Item order, Item set, session language, and Turn text selection are identical with and without instruction-like text in those fields.
3. WHEN a Transcribed_Answer contains instruction-like text such as "ignore your instructions" or "say something else", THE Answer_Mapper SHALL return an Unclear_Result unless the text also matches exactly one allowed value of the current Item, in which case THE Answer_Mapper SHALL return that single allowed value.
4. WHEN a Transcribed_Answer contains a request to change language, to reveal the questions or rules, or to skip the survey in words that are not one of the skip, not-now, or opt-out phrases of Requirement 11 criteria 3 to 5, THE JAAK_Engine SHALL leave the session language, the Item order, the Item set, and the count of answered Items unchanged, and SHALL NOT output any Survey text other than the current Item's own text or the re-ask template.
5. THE JAAK_Engine SHALL select Turn text only by code paths over the Survey fields and the fixed template set, and SHALL NOT select Turn text from Transcribed_Answer content.
6. FOR ALL Transcribed_Answers that do not match an allowed value, THE set of Turns produced SHALL be a subset of the Survey texts and the fixed template set, and no Turn SHALL contain any substring of 20 or more consecutive characters copied from the Transcribed_Answer unless that substring is also present in the Survey texts or fixed template set.
7. IF a Transcribed_Answer is empty or contains only whitespace, THEN THE Answer_Mapper SHALL return an Unclear_Result, THE JAAK_Engine SHALL keep the current Item unanswered, and THE JAAK_Engine SHALL produce only a Turn from the fixed template set.
8. IF a Transcribed_Answer is longer than 2,000 characters, THEN THE JAAK_Engine SHALL reject the call per Requirement 20 criterion 7, with an error, with the Dialogue_Session state and recorded answers unchanged, and with no Turn produced.

### Requirement 19: Logging and rejection handling

**User Story:** As an operator, I want every rejected input logged with a reason, so that I can find bad data without it leaking onward.

#### Acceptance Criteria

1. WHEN the JAAK_Engine rejects data at a Boundary, THE JAAK_Engine SHALL write exactly one Rejection_Log entry containing the Boundary name, the `survey_id` and `farmer_id` for each identifier present in the rejected data, the path of every field that failed validation, and a reason for each failing field.
2. IF the rejected data contains no `survey_id` and no `farmer_id`, THEN THE JAAK_Engine SHALL write the Rejection_Log entry with those identifiers recorded as absent and SHALL still include the Boundary name, failing field paths, and reason.
3. WHEN the JAAK_Engine rejects data at a Boundary, THE JAAK_Engine SHALL pass 0 bytes of the rejected data to any later step, and SHALL NOT change the state of any Dialogue_Session or stored record as a result of the rejected data.
4. THE Rejection_Log SHALL contain no `farmer_name` key and no `farmer_name` value, including inside the failing field paths and reason of every entry.
5. WHEN a Dialogue_Session ends, THE JAAK_Engine SHALL write exactly one log entry containing the `survey_id`, `farmer_id`, final `status`, `failure_code` (recorded as absent when the session did not fail), and the count of Items answered as an integer from 0 to the total number of Items in the survey, plus the closing-not-delivered indicator when Requirement 14 criterion 7 applies.
6. IF the JAAK_Engine fails to write a Rejection_Log entry, THEN THE JAAK_Engine SHALL still reject the data, pass none of it to any later step, and surface a logging-failure indication to the operator.

### Requirement 20: Text-only scope and extension points

**User Story:** As a developer of the next spec, I want clear seams for voice and UI, so that those parts plug in without changes to the core.

#### Acceptance Criteria

1. THE JAAK_Engine SHALL accept as input only text strings (each at most 2,000 characters) and caller-reported events, and SHALL return as output only text Turns and a Response_Record.
2. THE JAAK_Engine SHALL not import any speech-to-text, text-to-speech, Streamlit, or AWS speech library, so that importing the JAAK_Engine package in an environment where none of those libraries are installed completes without error.
3. THE JAAK_Engine SHALL expose an interface with exactly these five operations: start a session, get the next Turn, submit a Transcribed_Answer, submit a caller event, and get the Response_Record.
4. WHILE a Dialogue_Session is active, THE JAAK_Engine SHALL make zero outbound network calls, as verified by running a full Dialogue_Session with network access disabled and observing no connection attempts and no failures.
5. THE JAAK_Engine SHALL reside in a new package or module under `mel_agent/` and SHALL leave the behaviour of every existing `mel_agent/` module unchanged, as verified by the existing `mel_agent/` test suite passing with the same results before and after the JAAK_Engine is added.
6. WHEN each of the five surveyed worked scenarios in `json/scenarios/` (scenarios 1 to 5) is run once in each supported language with scripted answers, THE JAAK_Engine SHALL produce 10 Response_Records (5 scenarios times 2 languages), each of which validates against `response.schema.json` with zero schema violations; for scenario 6 (a `no_survey` case), a check SHALL confirm that the no_survey document validates against `no_survey.schema.json` and that no Dialogue_Session is started. Second-language Surveys, where not shipped in the pack, SHALL be hand-written test fixtures stored under `tests/fixtures`, not generated or translated by the JAAK_Engine, and no file under `data/participant-pack/` SHALL be modified.
7. IF an operation is called with input that is not a text string, exceeds 2,000 characters, or refers to an unknown or ended Dialogue_Session, THEN THE JAAK_Engine SHALL reject the call with an error indicating the invalid input or session, and SHALL leave the Dialogue_Session state and any recorded answers unchanged.

## Assumptions

1. **Persona vs. privacy.** The persona text says "You are talking to {user_name}", while the hard rules forbid asking for or repeating personal information. We resolve this as follows: the only name JAAK may use is a synthetic `farmer_name` from the Farmer_Name_Copy; it is used once, in the greeting Turn, as the fourth permitted text source defined in Requirement 16 criterion 1; and it is never stored in the Response_Record or logs. When no name is present, JAAK greets without a name. JAAK never asks for a name.
2. **Persona line wait.** "Wait for the farmer to finish" is modelled as the caller marking an utterance complete (Requirement 5.8), since text-only mode has no audio endpointing.
3. **Language source.** The Survey `language` is authoritative. The farmers.csv `language` is a consistency check only. Both are the same in all current scenarios.
4. **Channel.** The Response_Record `channel` is always `voice`, because JAAK is a voice agent even though this spec is text only.
5. **Caller events.** Events that JAAK cannot see in text (no answer, busy, call dropped, window expired, identity mismatch, duplicate) are reported by the caller. The later voice spec produces them.
6. **Fixed templates.** The greeting, lead-ins, re-ask, advice-decline, and closing lines are fixed templates in hi-IN and en-IN. Their wording is a design decision; a Hindi speaker should review the Hindi templates.
7. **Matching approach.** Answer mapping is deterministic (normalised exact and keyword matching with a number-word table). No language model is called. This satisfies "never guess" and Requirement 16.5.
8. **Yes and no vocabulary.** For `survey-confirm` Items the values are `yes` and `no` as in the scenarios, and the mapper also accepts common spoken forms in each language (for example "haan", "nahin", "ji haan").
9. **Scale range.** The scale numbers recognised by word are limited to 0 to 10, which covers all scenarios (1 to 5).
10. **Skip detection.** Skip, not now, and opt-out phrases are matched from a small fixed phrase list per language. Opt-out on a call is also the `9` key in `outcome_codes.json`; in text mode the phrase list is used.
11. **Counting toward the cap.** For records from `outcome_codes.json`, `counts_toward_cap` follows the file; for success records it is true.
12. **Existing code.** `mel_agent/responses.py` already builds records for simulated farmers; JAAK does not reuse its simulator but follows the same field conventions.
13. **No timers.** The JAAK_Engine owns no timers and reacts only to caller-signalled timeouts.
14. **Latency.** Latency bounds belong to the later voice spec, not to this text-only engine.

## Open Questions

1. **Keypad outcomes.** The outcome code `keypad_out_of_range` applies to voice. Should the text-only engine support a keypad input mode, or leave it for the voice spec?
2. **Scale mapping from spoken numbers.** How should the engine treat Hindi number words with spelling variants (for example "paanch", "पाँच", "पांच") and mixed phrases ("four out of five")? Is partial credit for ranges such as "three or four" correct as unclear? This spec treats it as unclear.
3. **Scale items with `scale_min` 0 or `scale_max` above 10.** Are these expected? The schema allows up to 100. The spec only requires number words up to 10.
4. **Mid-survey hang-up vs. partial.** When a call drops after some answers, the spec records `voice_call_dropped` (status `delivery_failed`, retry same channel after 10 minutes) and keeps the answers. The `partial` status means "skipped before the window closed". Which one should win when the farmer hangs up on purpose? Can JAAK tell the difference in text mode?
5. **Hang-up with all answers accepted but closing not heard.** Should this be `completed`?
6. **Bad outcomes on scale and options.** `follow_up_reason` appears both on Options and on Scale_Items with a threshold. If an Item has both an option flag and the same reason from another Item, we de-duplicate. Should a scale answer between the threshold and `scale_max` ever flag? And should a flagged answer on an Item that was only accepted on the second attempt be handled differently?
7. **Location of the Farmer_Name_Copy.** Where should the copy of farmers.csv with `farmer_name` live (for example `data/jaak/farmers_named.csv`, outside `participant-pack/`)? Who generates the synthetic names, and in which script (Devanagari for hi-IN, Latin for en-IN)?
8. **Name pronunciation.** If the later voice spec reads a Devanagari or Latin name aloud, who checks the pronunciation?
9. **`survey_closed`, `survey_replaced`, `free_text_instead_of_choice`.** These are not listed for voice in `outcome_codes.json` (`voice/survey_closed` is marked not applicable). The spec rejects them for voice. Confirm.
10. **Advice questions from the farmer.** Requirement 16.2 has JAAK say it cannot advise and refer to FarmerChat. Does Digital Green want a specific wording or a different hand-off?
11. **Phone-number redaction threshold.** The spec redacts digit runs of 7 or more in `raw_input`. Is this the right threshold, and should the whole `raw_input` be replaced?
12. **Timestamps.** What are `sent`, `delivered`, and `opened` for a voice call in text mode? The spec has the caller supply them, with null as the default.
13. **Greeting content.** Should the greeting name the topic (for example the crop) from the Survey? The Survey has no topic field, and using the Insight would break Requirement 16.4. The spec uses a generic line.
14. **`farmerchat_reply`.** The spec sets this to null because JAAK does not post to FarmerChat. Confirm the later spec fills it in.

15. **Redacted answers and the attempt count (Requirement 17.6 and 17.7 vs. 10.1 to 10.3).** A redacted answer is treated as an Unclear_Result, which consumes an attempt, so a farmer who volunteers a phone number twice gets the Item marked `invalid`. Confirm that this is intended. Also confirm how `raw_input` is set when the Transcribed_Answer is redacted but the Item is later answered.
16. **All Items skipped.** When every Item is skipped, none is answered, and the caller reports no failure, which Outcome_Code and status does the Response_Record carry? `outcome_codes.json` has no voice code for this case, and `partial` requires at least one answer.
17. **Item-level `speech_not_understood`.** The Response_Record has a single `failure_code`, and Requirement 12 criterion 2 gives a partial record a null `failure_code`. Where is the per-Item `speech_not_understood` recorded when other Items were answered (for example in the item entry only)?
18. **`identity_mismatch` and `duplicate_answer` handling.** `outcome_codes.json` describes `identity_mismatch` as "Not stored" and `duplicate_answer` as "The first answer stands", while Requirement 11 criteria 11, 12 and 16 keep accepted answers and set `answered_by` to the reported identity. Should `answers` be empty and `answered_by` null for these two codes?
