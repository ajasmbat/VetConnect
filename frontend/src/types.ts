export interface Address {
  address_1?: string | null;
  address_2?: string | null;
  address_3?: string | null;
  city?: string | null;
  state?: string | null;
  zip?: string | null;
}

export interface Facility {
  id: string;
  name: string;
  type?: string | null;
  classification?: string | null;
  address: Address;
  phone?: string | null;
  lat?: number | null;
  long?: number | null;
  services: string[];
  hours: Record<string, string | null>;
  website?: string | null;
  distance?: number | null;
}

export interface SearchResponse {
  count: number;
  facilities: Facility[];
}

export interface AssistantResponse {
  answer: string;
  parsed_service?: string | null;
  parsed_location?: string | null;
  facilities: Facility[];
}
