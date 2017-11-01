import difflib
import os
import re
import string

import lxml.etree as et
import unidecode

from transformations import (filename_to_doi, EXT_URL_TMP, INT_URL_TMP,
                             BASE_URL_ARTICLE_LANDING_PAGE)
from plos_regex import (validate_doi, corpusdir)
from samples.corpus_analysis import parse_article_date


def get_rid_dict(contrib_element):
    rid_dict = {}
    contrib_elements = contrib_element.getchildren()
    # get list of ref-types
    rid_type_list = [el.attrib['ref-type'] for el in contrib_elements if el.tag == 'xref']
    # make dict of ref-types to the actual ref numbers (rids)
    for rid_type in set(rid_type_list):
        rid_list = [el.attrib['rid'] for el in contrib_elements if el.tag == 'xref' and el.attrib['ref-type'] == rid_type]
        rid_dict[rid_type] = rid_list

    return rid_dict


def get_author_type(contrib_element):

    answer_dict = {
        "yes": "corresponding",
        "no": "contributing"
    }

    author_type = None
    if contrib_element.attrib['contrib-type'] == 'author':
        corr = contrib_element.get('corresp', None)
        if corr:
            author_type = answer_dict.get(corr, None)
        else:
            temp = get_rid_dict(contrib_element).get('corresp', None)
            if temp:
                author_type = answer_dict.get("yes", None)
            else:
                author_type = answer_dict.get("no", None)

    return author_type

    # TODO: check reftype when your are finding the string "cor" in rids
    # TODO: check assumption that all of the keys for the corresponding xref tag are "corresp"


def get_contrib_name(contrib_element):
    given_names = ''
    surname = ''
    contrib_name = {}

    contrib_name_element = contrib_element.find("name")
    try:
        for name_element in contrib_name_element.getchildren():
            if name_element.tag == 'surname':
                # for some reason, name_element.text doesn't work for this element
                surname = et.tostring(name_element,
                                      encoding='unicode',
                                      method='text').rstrip(' ').rstrip('\t').rstrip('\n')
            elif name_element.tag == 'given-names':
                given_names = name_element.text
                if given_names == '':
                    print("given names element.text didn't work")
                    given_names = et.tostring(name_element,
                                              encoding='unicode',
                                              method='text').rstrip(' ').rstrip('\t').rstrip('\n')
            else:
                pass
    except AttributeError:
        print("Contrib name element error: {}".format(contrib_name_element, contrib_element))
        surname = ''
        given_names = ''

    if bool(given_names) and bool(surname):
        try:
            contrib_initials = ''.join([part[0].upper() for part in re.split('[-| |,|\.]+', given_names) if part]) + \
                              ''.join([part[0] for part in re.split('[-| |,|\.]+', surname) if part[0] in string.ascii_uppercase])
        except IndexError:
            print("Can't construct initials for {} {}, {}".format(given_names, surname, contrib_element))
            contrib_initials = ''
        contrib_name = dict(contrib_initials=contrib_initials,
                            given_names=given_names,
                            surname=surname)
        return contrib_name
    else:
        return None


def get_contrib_info(contrib_element):
    # rid_dict = get_rid_dict(contrib_element)
    # return dict(
    #     rid_dict=rid_dict,
    #     contrib_name=get_contrib_name(contrib_element),
    #     author_type=get_author_type(contrib_element),
    #     corresp=rid_dict.get("corresp", None)
    #     )
    # get their name
    contrib_dict = get_contrib_name(contrib_element)
    # get contrib type
    contrib_dict['contrib_type'] = contrib_element.attrib['contrib-type']
    # get author type
    if contrib_dict.get('contrib_type') == 'author':
        contrib_dict['author_type'] = get_author_type(contrib_element)
    elif contrib_dict.get('contrib_type') == 'editor':
        for item in contrib_element.getchildren():
            if item.tag == 'Role' and item.text.lower() != 'editor':
                print('new editor type: {}'.format(item.text))
                contrib_dict['editor_type'] = item.text

    # get dictionary of contributor's footnote types to footnote ids
    contrib_dict['rid_dict'] = get_rid_dict(contrib_element)
    return contrib_dict


def match_author_to_email(corr_author, email_dict, matched_keys):
    corr_author_initials = corr_author.get('contrib_initials')
    # email_dict keys (initials) are assumed to be uppercase
    email_dict = {k.upper(): v 
                  for k, v in email_dict.items()
                  if k not in matched_keys}

    try:
        corr_author['email'] = email_dict[corr_author_initials.upper()]
    except KeyError:
        try:
            corr_author_abbrev_initials = ''.join([corr_author_initials[0], corr_author_initials[-1]])
            for email_initials, email_address in email_dict.items():
                if corr_author_abbrev_initials == ''.join([email_initials[0], email_initials[-1]]).upper():
                    corr_author['email'] = email_address
                    break
        except KeyError:
            pass
    if 'email' not in corr_author:
        for email_initials, email_address in email_dict.items():
            seq_1 = unidecode.unidecode(''.join([corr_author.get('given_names'), corr_author.get('surname')]).lower())
            seq_2 = unidecode.unidecode(email_address[0].lower().split('@')[0])
            print('seq 2: {}'.format(seq_2))
            matcher = difflib.SequenceMatcher(a=seq_1, b=seq_2)
            match = matcher.find_longest_match(0, len(matcher.a), 0, len(matcher.b))
            if match[-1] >= 5:
                print("match ok {}:{}, {} letters".format(seq_1, seq_2, match[-1]))
                corr_author['email'] = email_address
                break
            elif 2 <= match[-1] <= 4:
                print('match ok?', seq_1[match.a: match.a + match.size], seq_1, seq_2)
    return corr_author


def match_authors_to_emails(corr_author_list, email_dict):
    matched_keys = []
    for corr_author in corr_author_list:
        corr_author = match_author_to_email(corr_author, email_dict, matched_keys)
        if corr_author.get('email', None):
            for k, v in email_dict.items():
                if v == corr_author.get('email'):
                    matched_keys.append(k)
    if len(email_dict) == len(matched_keys):
        pass
    else:
        unmatched_email_dict = {k: v for k, v in email_dict.items() if k not in matched_keys}
        corr_author_missing_email_list = [corr_author for corr_author in corr_author_list if not corr_author.get('email', None)]
        if len(unmatched_email_dict) == len(corr_author_missing_email_list) == 1:
            print('Nuclear option engaged!')
            corr_author_missing_email_list[0]['email'] = list(unmatched_email_dict.values())[0]
    return corr_author_list


class Article(object):
    plos_prefix = ''

    def __init__(self, doi, directory=None):
        self.doi = doi
        if directory is None:
            self.directory = corpusdir
        else:
            self.directory = directory
        self.reset_memoized_attrs()

    def reset_memoized_attrs(self):
        self._tree = None
        self._local = None
        self._correct_or_retract = None  # Will probably need to be an article subclass        

    @property
    def doi(self):
        return self._doi

    @doi.setter
    def doi(self, d):
        if validate_doi(d) is False:
            raise Exception("Invalid format for PLOS DOI")
        self.reset_memoized_attrs()
        self._doi = d

    def get_path(self):
        if 'annotation' in self.doi:
            article_path = os.path.join(self.directory, 'plos.correction.' + self.doi.split('/')[-1] + '.xml')
        else:
            article_path = os.path.join(self.directory, self.doi.lstrip('10.1371/') + '.xml')
        return article_path

    def get_local_bool(self):
        article_path = self.get_path()
        return os.path.isfile(article_path)

    def get_local_element_tree(self, article_path=None):
        if article_path is None:
            article_path = self.get_path()
        if self.local:
            local_element_tree = et.parse(article_path)
            return local_element_tree
        else:
            print("Local article file not found: {}".format(article_path))

    def get_local_root_element(self, article_tree=None):
        if article_tree is None:
            article_tree = self.tree
        root = article_tree.getroot()
        return root

    def get_local_xml(self, article_tree=None, pretty_print=True):
        if article_tree is None:
            article_tree = self.tree
        local_xml = et.tostring(article_tree,
                                method='xml',
                                encoding='unicode',
                                pretty_print=pretty_print)
        return print(local_xml)

    def get_landing_page(self):
        return BASE_URL_ARTICLE_LANDING_PAGE + self.doi

    def get_url(self, plos_network=False):
        URL_TMP = INT_URL_TMP if plos_network else EXT_URL_TMP
        return URL_TMP.format(self.doi)

    def get_remote_element_tree(self, url=None):
        if url is None:
            url = self.get_url()
        remote_element_tree = et.parse(url)
        return remote_element_tree

    def get_remote_xml(self, article_tree=None, pretty_print=True):
        if article_tree is None:
            article_tree = self.get_remote_element_tree()
        remote_xml = et.tostring(article_tree,
                                 method='xml',
                                 encoding='unicode',
                                 pretty_print=pretty_print)
        return print(remote_xml)

    def get_element_xpath(self, article_root=None, tag_path_elements=None):
        """
        For a local article's root element, grab particular sub-elements via XPath location
        Defaults to reading the element location for uncorrected proofs/versions of record
        :param article_root: the xml file for a single article
        :param tag_path_elements: xpath location in the XML tree of the article file
        :return: list of elements with that xpath location
        """
        if article_root is None:
            article_root = self.root
        if tag_path_elements is None:
            tag_path_elements = ('/',
                                 'article',
                                 'front',
                                 'article-meta',
                                 'custom-meta-group',
                                 'custom-meta',
                                 'meta-value')
        tag_location = '/'.join(tag_path_elements)
        return article_root.xpath(tag_location)

    def get_proof_status(self):
        """
        For a single article in a directory, check whether it is an 'uncorrected proof' or a
        'VOR update' to the uncorrected proof, or neither
        :return: proof status if it exists; otherwise, None
        """
        xpath_results = self.get_element_xpath()
        for result in xpath_results:
            if result.text == 'uncorrected-proof':
                return 'uncorrected_proof'
            elif result.text == 'vor-update-to-uncorrected-proof':
                return 'vor_update'
            else:
                pass
        return None

    def get_plos_journal(self, caps_fixed=True):
        """
        For an individual PLOS article, get the journal it was published in.
        :param caps_fixed: whether to render 'PLOS' in the journal name correctly or as-is ('PLoS')
        :return: PLOS journal at specified xpath location
        """
        try:
            journal = self.get_element_xpath(tag_path_elements=["/",
                                                                "article",
                                                                "front",
                                                                "journal-meta",
                                                                "journal-title-group",
                                                                "journal-title"])
            journal = journal[0].text
        except IndexError:
            # Need to file JIRA ticket: only affects pone.0047704
            journal_meta = self.get_element_xpath(tag_path_elements=["/",
                                                                     "article",
                                                                     "front",
                                                                     "journal-meta"])
            for journal_child in journal_meta[0]:
                if journal_child.attrib['journal-id-type'] == 'nlm-ta':
                    journal = journal_child.text
                    break

        if caps_fixed:
            journal = journal.split()
            if journal[0].lower() == 'plos':
                journal[0] = "PLOS"
            journal = (' ').join(journal)
        return journal

    def get_article_title(self):
        """
        For an individual PLOS article, get its title.
        :return: string of article title at specified xpath location
        """
        title = self.get_element_xpath(tag_path_elements=["/",
                                                          "article",
                                                          "front",
                                                          "article-meta",
                                                          "title-group",
                                                          "article-title"])
        title_text = et.tostring(title[0], encoding='unicode', method='text', pretty_print=True)
        return title_text.rstrip('\n')

    def get_dates(self, string_=False, string_format='%Y-%m-%d', debug=False):
        """
        For an individual article, get all of its dates, including publication date (pubdate), submission date
        :return: dict of date types mapped to datetime objects for that article
        """
        dates = {}

        tag_path_1 = ["/",
                      "article",
                      "front",
                      "article-meta",
                      "pub-date"]
        element_list_1 = self.get_element_xpath(tag_path_elements=tag_path_1)
        for element in element_list_1:
            pub_type = element.get('pub-type')
            try:
                date = parse_article_date(element)
            except ValueError:
                print('Error getting pubdates for {}'.format(self.doi))
                date = ''
            dates[pub_type] = date

        tag_path_2 = ["/",
                      "article",
                      "front",
                      "article-meta",
                      "history"]
        element_list_2 = self.get_element_xpath(tag_path_elements=tag_path_2)
        for element in element_list_2:
            for part in element:
                date_type = part.get('date-type')
                try:
                    date = parse_article_date(part)
                except ValueError:
                    print('Error getting history dates for {}'.format(self.doi))
                    date = ''
                dates[date_type] = date
        if debug:
            # check whether date received is before date accepted is before pubdate
            if dates.get('received', '') and dates.get('accepted', '') in dates:
                if not dates['received'] <= dates['accepted'] <= dates['epub']:
                    print('{}: dates in wrong order'.format(self.doi))

        if string_:
            # can return dates as strings instead of datetime objects if desired
            for key, value in dates.items():
                if value:
                    dates[key] = value.strftime(string_format)

        return dates

    def get_pubdate(self, string_=False, string_format='%Y-%m-%d'):
        dates = self.get_dates(string_=string_, string_format=string_format)
        return dates['epub']

    def get_aff_dict(self):
        """For a given PLOS article, get list of contributor-affiliated institutions.

        Used to map individual contributors to their institutions
        :returns: Dictionary of footnote ids to institution information
        :rtype: {[dict]}
        """
        # TO DO: sometimes for editors, the affiliation is in the same element
        tags_to_aff = ["/",
                       "article",
                       "front",
                       "article-meta"]
        article_meta_element = self.get_element_xpath(tag_path_elements=tags_to_aff)[0]
        aff_dict = {}
        aff_elements = [el for el in article_meta_element.getchildren() if el.tag == 'aff']
        for el in aff_elements:
            for sub_el in el.getchildren():
                if sub_el.tag == 'addr-line':
                    aff_dict[el.attrib['id']] = sub_el.text
        return aff_dict

    def get_corr_author_emails(self):
        tag_path = ["/",
                    "article",
                    "front",
                    "article-meta",
                    "author-notes"]
        author_notes_element = self.get_element_xpath(tag_path_elements=tag_path)[0]
        corr_emails = {}
        email_list = []
        for note in author_notes_element:
            if note.tag == 'corresp':
                author_info = note.getchildren()
                for i, item in enumerate(author_info):
                    # if no author initials (one corr author)
                    if item.tag == 'email' and item.tail is None and item.text:
                        email_list.append(item.text)
                        if item.text == '':
                            print('No email available for {}'.format(self.doi))
                        corr_emails[note.attrib['id']] = email_list
                    # if more than one email per author
                    elif item.tag == 'email' and ',' in item.tail:
                        if author_info[i+1].tail is None:
                            email_list.append(item.text)
                        elif author_info[i+1].tail:
                            corr_initials = re.sub(r'[^a-zA-Z0-9=]', '', author_info[i+1].tail)
                            if not corr_emails.get(corr_initials):
                                corr_emails[corr_initials] = [item.text]
                            else:
                                corr_emails[corr_initials].append(item.text)
                        if item.text == '':
                            print('No email available for {}'.format(self.doi))
                    # if author initials included (more than one corr author)
                    elif item.tag == 'email' and item.tail:
                        corr_email = item.text
                        corr_initials = re.sub(r'[^a-zA-Z0-9=]', '', item.tail)
                        if not corr_emails.get(corr_initials):
                            corr_emails[corr_initials] = [corr_email]
                        else:
                            corr_emails[corr_initials].append(corr_email)
                    else:
                        pass
        return corr_emails

    def get_contributors_info(self):
        # TODO: add ORCID, param to remove unnecessary fields (initials) and dicts (rid_dict)
        # get dictionary of footnote ids to institutional affiliations
        aff_dict = self.get_aff_dict()
        # get dictionary of corresponding author email addresses
        email_dict = self.get_corr_author_emails()
        # get list of contributor elements (one per contributor)
        tag_path = ["/",
                    "article",
                    "front",
                    "article-meta",
                    "contrib-group",
                    "contrib"]
        contrib_list = self.get_element_xpath(tag_path_elements=tag_path)
        contrib_dict_list = []
        for contrib in contrib_list:
            contrib_dict = get_contrib_info(contrib)

            # get dictionary of contributor's footnote types to footnote ids
            contrib_dict['rid_dict'] = get_rid_dict(contrib)

            # map affiliation footnote ids to the actual institutions
            contrib_dict['affiliations'] = [aff_dict[aff] for aff in contrib_dict['rid_dict'].get('aff')]

            contrib_dict_list.append(contrib_dict)

        corr_author_list = [contrib for contrib in contrib_dict_list if contrib.get('author_type', None) == 'corresponding']
        if not corr_author_list and email_dict:
            print('Corr authors but no emails found for {}'.format(self.doi))
        if corr_author_list and not email_dict:
            print('Corr emails not found for {}'.format(self.doi))
        if len(corr_author_list) == 1:
            corr_author = corr_author_list[0]
            corr_author['email'] = email_dict[corr_author['rid_dict']['corresp'][0]]
        elif len(corr_author_list) > 1:
            for corr_author in corr_author_list:
                corr_author = match_authors_to_emails(corr_author, email_dict)

        return contrib_dict_list


    def get_jats_article_type(self):
        """
        For an article file, get its JATS article type
        Use primarily to find Correction (and thereby corrected) articles
        :return: JATS article_type at that xpath location
        """
        type_element_list = self.get_element_xpath(tag_path_elements=["/",
                                                                      "article"])
        return type_element_list[0].attrib['article-type']

    def get_plos_article_type(self):
        """
        For an article file, get its PLOS article type. This format is less standardized than JATS article type
        :return: PLOS article_type at that xpath location
        """
        article_categories = self.get_element_xpath(tag_path_elements=["/",
                                                                       "article",
                                                                       "front",
                                                                       "article-meta",
                                                                       "article-categories"])
        subject_list = article_categories[0].getchildren()

        for i, subject in enumerate(subject_list):
            if subject.get('subj-group-type') == "heading":
                subject_instance = subject_list[i][0]
                s = ''
                for text in subject_instance.itertext():
                    s = s + text
                    plos_article_type = s
        return plos_article_type

    def get_dtd(self):
        """
        For more information on these DTD tagsets, see https://jats.nlm.nih.gov/1.1d3/ and https://dtd.nlm.nih.gov/3.0/
        """
        try:
            dtd = self.get_element_xpath(tag_path_elements=["/",
                                                            "article"])
            dtd = dtd[0].attrib['dtd-version']
            if str(dtd) == '3.0':
                dtd = 'NLM 3.0'
            elif dtd == '1.1d3':
                dtd = 'JATS 1.1d3'
        except KeyError:
            print('Error parsing DTD from', self.doi)
            dtd = 'N/A'
        return dtd

    def get_abstract(self):
        """
        For an individual article in the PLOS corpus, get the string of the abstract content.
        :return: plain-text string of content in abstract
        """
        abstract = self.get_element_xpath(tag_path_elements=["/",
                                                             "article",
                                                             "front",
                                                             "article-meta",
                                                             "abstract"])
        try:
            abstract_text = et.tostring(abstract[0], encoding='unicode', method='text')
        except IndexError:
            if self.type_ == 'research-article' and self.plostype == 'Research Article':
                print('No abstract found for research article {}'.format(self.doi))

            abstract_text = ''

        # clean up text: rem white space, new line marks, blank lines
        abstract_text = abstract_text.strip().replace('  ', '')
        abstract_text = os.linesep.join([s for s in abstract_text.splitlines() if s])

        return abstract_text

    def correct_or_retract_bool(self):
        if self.type_ == 'correction' or self.type_ == 'retraction':
            self._correct_or_retract = True
        else:
            self._correct_or_retract = False
        return self._correct_or_retract

    def get_related_doi(self):
        """
        For an article file, get the DOI of the first related article
        More strict in tag search if article is correction type
        Use primarily to map correction and retraction notifications to articles that have been corrected
        NOTE: what to do if more than one related article?
        :return: doi at that xpath location
        """
        related_article_elements = self.get_element_xpath(tag_path_elements=["/",
                                                                             "article",
                                                                             "front",
                                                                             "article-meta",
                                                                             "related-article"])
        related_article = ''
        if self.type_ == 'correction':
            for element in related_article_elements:
                if element.attrib['related-article-type'] in ('corrected-article', 'companion'):
                    corrected_doi = element.attrib['{http://www.w3.org/1999/xlink}href']
                    related_article = corrected_doi.lstrip('info:doi/')
                    break
        else:
            related_article_element = related_article_elements[0].attrib
            related_article = related_article_element['{http://www.w3.org/1999/xlink}href']
            related_article = related_article.lstrip('info:doi/')
        return related_article

    def get_counts(self):
        """
        For a single article, return a dictionary of the several counts functions that are available
        (figures: fig-count, pages: page-count, tables: table-count)
        :return: counts dictionary
        """
        counts = {}

        tag_path = ["/",
                    "article",
                    "front",
                    "article-meta",
                    "counts"]
        count_element_list = self.get_element_xpath(tag_path_elements=tag_path)
        for count_element in count_element_list:
            for count_item in count_element:
                count = count_item.get('count')
                count_type = count_item.tag
                counts[count_type] = count
        if len(counts) > 3:
            print(counts)
        return counts

    def get_body_word_count(self):
        """
        For an article, get how many words are in the body
        :return: count of words in the body of the PLOS article
        """
        body_element = self.get_element_xpath(tag_path_elements=["/",
                                                                 "article",
                                                                 "body"])
        try:
            body_text = et.tostring(body_element[0], encoding='unicode', method='text')
            body_word_count = len(body_text.split(" "))
        except IndexError:
            print("Error parsing article body: {}".format(self.doi))
            body_word_count = 0
        return body_word_count

    @property
    def xml(self):
        return self.get_local_xml()

    @property
    def tree(self):
        if self._tree is None:
            return self.get_local_element_tree()
        else:
            return self._tree

    @property
    def root(self):
        return self.get_local_root_element()

    @property
    def page(self):
        return self.get_landing_page()

    @property
    def url(self):
        return self.get_url(plos_network=self.plos_network)

    @property
    def filename(self):
        return self.get_path()

    @property
    def local(self):
        if self._local is None:
            return self.get_local_bool()
        else:
            return self._local

    @property
    def proof(self):
        return self.get_proof_status()

    @property
    def journal(self):
        return self.get_plos_journal()

    @property
    def title(self):
        return self.get_article_title()

    @property
    def pubdate(self):
        return self.get_pubdate()

    @property
    def authors(self):
        contributors = self.get_contributors_info()
        return [contrib for contrib in contributors if contrib.get('contrib_type', None) == 'author']       

    @property
    def corr_author(self):
        contributors = self.get_contributors_info()
        return [contrib for contrib in contributors if contrib.get('author_type', None) == 'corresponding']

    @property
    def editor(self):
        contributors = self.get_contributors_info()
        return [contrib for contrib in contributors if contrib.get('contrib_type', None) == 'editor']

    @property
    def type_(self):
        return self.get_jats_article_type()

    @property
    def plostype(self):
        return self.get_plos_article_type()

    @property
    def dtd(self):
        return self.get_dtd()

    @property
    def abstract(self):
        return self.get_abstract()

    @property
    def correct_or_retract(self):
        if self._correct_or_retract is None:
            return self.correct_or_retract_bool()
        else:
            return self._correct_or_retract

    @property
    def related_doi(self):
        if self.correct_or_retract is True:
            return self.get_related_doi()
        else:
            return None

    @property
    def counts(self):
        return self.get_counts()

    @property
    def word_count(self):
        return self.get_body_word_count()

    @filename.setter
    def filename(self, value):
        self.doi = filename_to_doi(value)

    @classmethod
    def from_filename(cls, filename):
        return cls(filename_to_doi(filename))
